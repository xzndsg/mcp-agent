"""Agent 运行时：LangChain Agent 编排 + 多轮会话 + 流式事件。

- LLM 使用 OpenAI 兼容接口（DeepSeek / 智谱 / OpenAI，可在配置中切换）；
- 每轮对话动态构建工具集（连接状态 / 启停变更实时生效）；
- 未配置任何 API Key 时自动进入"本地演示模式"，保证骨架与 UI 链路始终可跑。
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

from .config import AppConfig, load_config
from .langchain_adapter import build_langchain_tools
from .local_tools import LocalToolKit
from .logging_utils import get_logger
from .memory import Memory, NullMemory
from .server_manager import ServerManager
from .session import DEFAULT_MAX_HISTORY, SessionManager
from .tool_registry import ToolRegistry

logger = get_logger("agent")


class AgentRuntime:
    def __init__(
        self,
        config: Optional[AppConfig] = None,
        manager: Optional[ServerManager] = None,
        local_kit: Optional[LocalToolKit] = None,
        registry: Optional[ToolRegistry] = None,
        memory: Optional[Memory] = None,
    ) -> None:
        self.config = config or load_config()
        self.manager = manager
        self.local_kit = local_kit or (manager.local_kit if manager is not None else None)
        self.registry = registry or (
            manager.registry if manager is not None else ToolRegistry()
        )
        self.sessions = SessionManager()
        self.memory = memory or NullMemory()

        self._llm: Optional[ChatOpenAI] = self._build_llm()
        if self._llm is None:
            logger.warning(
                "未检测到 LLM API Key，Agent 以本地演示模式运行（配置 .env 后启用模型决策）"
            )

    # ============================================================== 构建

    def _build_llm(self) -> Optional[ChatOpenAI]:
        if not self.config.llm_ready:
            return None
        return ChatOpenAI(
            model=self.config.llm_model,
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_base_url,
            temperature=self.config.llm_temperature,
        )

    @property
    def llm_ready(self) -> bool:
        return self._llm is not None

    def _build_executor(self) -> AgentExecutor:
        tools = build_langchain_tools(self.registry, self.manager, self.local_kit)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.config.system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder(variable_name="agent_scratchpad"),
            ]
        )
        agent = create_tool_calling_agent(self._llm, tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=tools,
            max_iterations=5,
            early_stopping_method="generate",
            handle_parsing_errors=True,
        )

    def _payload(self, session_id: str, message: str) -> dict[str, Any]:
        session = self.sessions.get_or_create(session_id)
        recalled = self.memory.recall(message, session_id)
        chat_history = session.recent_history(DEFAULT_MAX_HISTORY)
        if recalled:
            hint = "可参考的长期记忆：\n" + "\n".join(f"- {item}" for item in recalled)
            chat_history = [HumanMessage(content=hint)] + chat_history
        return {"input": message, "chat_history": chat_history}

    def enabled_tool_names(self) -> list[str]:
        return [tool["name"] for tool in self.registry.get_enabled_tools()]

    # ============================================================== 对话

    def chat(self, session_id: str, message: str) -> dict[str, Any]:
        """同步对话，返回 {session_id, reply, llm_ready, tools}。"""
        sid = session_id or self.sessions.new_id()
        session = self.sessions.get_or_create(sid)

        if not self.llm_ready:
            reply = self._demo_reply(message)
        else:
            reply = self._chat_with_llm(sid, message)

        session.append(HumanMessage(content=message))
        session.append(AIMessage(content=reply))
        self._safe_remember(message, sid, "user")
        self._safe_remember(reply, sid, "assistant")
        return {
            "session_id": sid,
            "reply": reply,
            "llm_ready": self.llm_ready,
            "tools": self.enabled_tool_names(),
        }

    def _chat_with_llm(self, session_id: str, message: str) -> str:
        try:
            executor = self._build_executor()
            result = executor.invoke(self._payload(session_id, message))
            return str(result.get("output", ""))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent 调用失败")
            return f"[Agent 调用失败] {type(exc).__name__}: {exc}"

    async def achat(self, session_id: str, message: str) -> dict[str, Any]:
        """异步对话。"""
        sid = session_id or self.sessions.new_id()
        session = self.sessions.get_or_create(sid)

        if not self.llm_ready:
            reply = self._demo_reply(message)
        else:
            try:
                executor = self._build_executor()
                result = await executor.ainvoke(self._payload(sid, message))
                reply = str(result.get("output", ""))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent 异步调用失败")
                reply = f"[Agent 调用失败] {type(exc).__name__}: {exc}"

        session.append(HumanMessage(content=message))
        session.append(AIMessage(content=reply))
        return {
            "session_id": sid,
            "reply": reply,
            "llm_ready": self.llm_ready,
            "tools": self.enabled_tool_names(),
        }

    async def astream(
        self, session_id: str, message: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式对话。事件类型：token / tool_start / tool_end / done / error。"""
        sid = session_id or self.sessions.new_id()
        session = self.sessions.get_or_create(sid)
        full_reply_parts: list[str] = []

        try:
            if not self.llm_ready:
                demo = self._demo_reply(message)
                # 按行简单分块，便于前端呈现打字效果
                for line in demo.splitlines(keepends=True):
                    full_reply_parts.append(line)
                    yield {"type": "token", "content": line}
            else:
                executor = self._build_executor()
                async for event in executor.astream_events(
                    self._payload(sid, message), version="v2"
                ):
                    kind = event.get("event")
                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        content = getattr(chunk, "content", "") or ""
                        if content:
                            full_reply_parts.append(content)
                            yield {"type": "token", "content": content}
                    elif kind == "on_tool_start":
                        yield {
                            "type": "tool_start",
                            "tool": event.get("name"),
                            "args": event.get("data", {}).get("input"),
                        }
                    elif kind == "on_tool_end":
                        output = event.get("data", {}).get("output")
                        yield {
                            "type": "tool_end",
                            "tool": event.get("name"),
                            "output": _shorten(output),
                        }

            reply = "".join(full_reply_parts).strip() or "(无回复)"
            session.append(HumanMessage(content=message))
            session.append(AIMessage(content=reply))
            self._safe_remember(message, sid, "user")
            self._safe_remember(reply, sid, "assistant")
            yield {
                "type": "done",
                "session_id": sid,
                "reply": reply,
                "llm_ready": self.llm_ready,
                "tools": self.enabled_tool_names(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent 流式调用失败")
            yield {"type": "error", "error": f"{type(exc).__name__}: {exc}"}

    # ============================================================== 辅助

    def _safe_remember(self, text: str, session_id: str, role: str) -> None:
        try:
            self.memory.remember(text, session_id, role)
        except Exception:  # noqa: BLE001
            pass

    def _demo_reply(self, message: str) -> str:
        tools = self.registry.get_enabled_tools()
        lines = [
            "【本地演示模式】未检测到 LLM API Key，模型决策未启用。",
            f"已收到消息：{message}",
            "",
        ]
        if tools:
            lines.append("当前可用工具（配置 Key 后将由模型自动决策调用）：")
            for tool in tools:
                desc = tool.get("description") or "（无描述）"
                lines.append(f"- {tool['name']}：{desc}")
        else:
            lines.append("当前没有可用工具，可在控制台添加 MCP Server 或注册本地工具。")
        lines.append("")
        lines.append("请在 .env 中配置 DEEPSEEK_API_KEY / ZHIPU_API_KEY / OPENAI_API_KEY 之一后重启。")
        return "\n".join(lines)


def _shorten(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[:limit] + " …(已截断)"
