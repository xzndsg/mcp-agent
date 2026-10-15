# mcp-agent

> 通用 MCP Agent 框架 —— **Flask 做服务外壳，LangChain 做智能内核，MCP 做业务连接，能力层做多模态**。
>
> 设计参考 [Fay](https://github.com/xszyou/Fay) 的 MCP 内核理念，沉淀为一个可嵌入、可二次开发的通用框架：统一管理 MCP 业务工具，并自带 **语音合成（Edge-TTS）、图片数字人、OpenAI 兼容接口平台** 等多模态能力。

## 它解决什么问题

业务系统（数据库、内部 API、SaaS、设备……）以 **MCP Server** 的形式暴露工具，本框架：

1. **统一接入**：同时管理多个 MCP Server，支持 `stdio` / `sse` / `streamable-http` 三种传输；
2. **统一编排**：把 MCP 工具自动适配为 LangChain 工具，由 LLM Agent 自主决策调用；
3. **统一对外**：REST + SSE、WebSocket 对话接口，并可把自身**反向暴露为 MCP Server**，接入 Claude Desktop 等 MCP 宿主；
4. **统一能力**：TTS / 数字人 / 视频生成等多模态能力以 Provider 插件化接入，并通过**接口平台**（能力发现 + OpenAI 兼容端点）供 Dify、Coze、自有前端直接对接；
5. **可观测、可降级**：连接状态/延迟/错误落盘，无 LLM Key 时自动进入本地演示模式，骨架永远可跑。

## 架构

```
                         ┌──────────────────────────── 终端层 ───────────────────────────┐
   网页 / APP / 业务系统  │  REST(/api/chat)  SSE(/api/chat/stream)  WebSocket(/ws)       │
                         └──────────────────────────────┬────────────────────────────────┘
                                                        │ Flask (mcp_agent.server)
        ┌───────────────────────┬───────────────────────┼────────────────────┬───────────────────┐
        │ mcp_admin_api          │ rest_api / ws_api      │ mcp_host            │ web 控制台         │
        │ MCP 服务器/工具管理     │ 对话与流式              │ 自举 MCP Server     │ (templates/static) │
        └───────────┬───────────┴────────────┬───────────┴─────────┬──────────┴───────────────────┘
                    │                        │                     │
                    ▼                        ▼                     ▼
┌──────────────────────────── core（纯 Python 内核，可脱离 Flask 单独使用）──────────────────────┐
│  ServerManager ── 多 MCP Server 生命周期 / 健康检查 / 配置持久化                                   │
│  McpClient    ── stdio / sse / streamable-http，独立线程事件循环                                  │
│  ToolRegistry ── 跨服工具聚合、available/enabled 状态（线程安全）                                  │
│  LocalToolKit ── 进程内 Python 函数直注册（不依赖子进程，演示永不失败）                             │
│  LangChainAdapter ── MCP Tool ⇄ StructuredTool（Pydantic v2 schema 动态生成）                     │
│  AgentRuntime ── LangChain Agent 工具决策 / 多轮会话 / 流式事件                                    │
│  SessionManager / Memory ── 多用户会话隔离（长期记忆为扩展点）                                     │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
                    ▲                                                            ▲
        外部 MCP Servers（stdio / SSE / HTTP）                     DeepSeek / 智谱 / OpenAI（OpenAI 兼容接口）
```

## 快速开始

环境要求 Python 3.11+。

```bash
# 1. 安装（建议在虚拟环境中）
pip install -e .

# 2. 配置 LLM（复制后填入任意一家的 Key；不填也能以演示模式启动）
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux

# 3. 启动服务（推荐统一入口）
python main.py
# 或：python main.py doctor    # 环境自检
# 或：mcp-agent start          # 等价 CLI
```

打开管理控制台 <http://127.0.0.1:5000>：

- **对话**：与 Agent 流式对话，工具由模型自动调用；
- **数字人**：上传一张人物照片，获得一个会呼吸、会眨眼、会说话的形象（Edge-TTS + 音频振幅驱动，零 GPU）；
- **语音**：TTS 合成试听 / 多音色选择 / 浏览器原生语音识别；
- **平台接口**：能力发现卡片 + OpenAI 兼容接入文档；
- **MCP 服务器 / 工具**：连接管理、跨服工具聚合与启停。

### 5 分钟体验一个自带工具的 MCP Server

```bash
# 终端 A：以 stdio 方式启动示例 MCP Server（echo + add 两个工具）
python examples/echo_mcp_server.py --transport stdio
```

在控制台 Servers 页新增：transport=`stdio`，command=`python`，args=`examples/echo_mcp_server.py`，点击连接即可看到两个工具。
也可以在终端 A 改用 `--transport streamable-http --port 8100`，再以 URL `http://127.0.0.1:8100/mcp/` 接入。

### 把本框架自身接入 Claude Desktop

```bash
mcp-agent serve --transport stdio
```

`mcp-agent serve` 会启动一个 MCP Server，对外暴露 `chat`、`list_available_tools` 等工具，宿主即可通过 MCP 协议调用本框架的 Agent 能力。

### 作为库嵌入

```python
from mcp_agent.core import AgentRuntime, ServerManager, ToolRegistry, LocalToolKit

kit = LocalToolKit()

@kit.register
def order_status(order_id: str) -> str:
    """根据订单号查询订单状态"""
    return f"订单 {order_id}：已发货"

manager = ServerManager()
runtime = AgentRuntime(manager=manager, local_kit=kit)
print(runtime.chat("default", "帮我查一下订单 A1001 的状态"))
```

更多示例见 [examples/](examples/)。

### 对接 Dify / Coze / OpenAI SDK（接口平台）

mcp-agent 对外暴露 **OpenAI 兼容端点**，第三方系统把 `BASE_URL` 指向本框架即可复用整个 Agent 内核与 MCP 工具生态：

```bash
BASE_URL=http://127.0.0.1:5000/v1
API_KEY=任意值（若服务端配置了 MCP_AGENT_API_TOKEN 则填该 Token）

curl http://127.0.0.1:5000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mcp-agent","messages":[{"role":"user","content":"你好"}],"stream":true}'
```

能力接口一览（`GET /api/v1/capabilities` 可动态发现）：

| 接口 | 说明 |
| --- | --- |
| `GET /api/v1/capabilities` | 多模态能力发现（providers / 可用状态） |
| `GET /api/v1/tts/voices` | TTS 音色列表 |
| `POST /api/v1/tts` | 文本合成语音，返回 `audio/mpeg` |
| `GET/POST /api/v1/digital_human` | 数字人配置与状态读写 |
| `GET/POST /api/v1/digital_human/image` | 获取 / 上传数字人形象图 |
| `POST /api/v1/digital_human/speak` | 数字人开口说话（TTS + speaking 状态） |
| `POST /v1/chat/completions` | OpenAI 兼容对话（支持 `stream`） |

## 多模态能力层（Provider 解耦）

所有能力都在 `mcp_agent/capabilities/` 中以 **Provider 协议** 接入，核心代码不依赖任何厂商 SDK：

| 能力 | 内置 Provider | 说明 / 扩展 |
| --- | --- | --- |
| 语音合成 TTS | `edge-tts`（微软，免费无 Key，7 音色） | 新增厂商 = 实现 `TTSProvider` 并注册 |
| 数字人 | `static-image`（CSS 呼吸/眨眼/音频振幅摆动，零 GPU） | 可替换为 SadTalker / EchoMimic 真渲染 |
| 视频生成 | `stub`（预留扩展位） | 接入即梦 / 可灵 / Runway 即可实现 `VideoProvider` |

数字人原理：后端只保存形象图与动画参数；前端用 CSS 动画叠加 WebAudio 音频振幅驱动"说话"。升级真渲染只需替换 provider，接口协议不变。

## 模块说明

| 模块 | 职责 |
| --- | --- |
| `mcp_agent/core/config.py` | 配置中心：三家 LLM 模板、数据目录、服务参数（.env / 环境变量） |
| `mcp_agent/core/mcp_client.py` | 单个 MCP Server 连接，独立线程事件循环，同步 + 协程双接口 |
| `mcp_agent/core/server_manager.py` | 多 Server 增删改查、连接 / 重连、定时健康检查、JSON 持久化 |
| `mcp_agent/core/tool_registry.py` | 工具注册中心：跨服聚合、启用状态、线程安全缓存 |
| `mcp_agent/core/local_tools.py` | 进程内本地工具：普通 Python 函数自动生成 JSON Schema |
| `mcp_agent/core/langchain_adapter.py` | MCP / 本地工具 → LangChain `StructuredTool` |
| `mcp_agent/core/agent.py` | Agent 运行时：模型工厂、工具决策、流式事件、无 Key 降级 |
| `mcp_agent/core/session.py` | 多用户会话与历史隔离 |
| `mcp_agent/capabilities/` | 多模态能力层：Provider 协议 + TTS / 视频 / 数字人实现 |
| `mcp_agent/server/gateway_api.py` | 接口平台网关：能力发现 / TTS / 数字人 / OpenAI 兼容端点 |
| `mcp_agent/server/rest_api.py` | `POST /api/chat`、`GET /api/chat/stream`(SSE)、会话管理 |
| `mcp_agent/server/mcp_admin_api.py` | MCP Server / 工具的管理 REST API |
| `mcp_agent/server/ws_api.py` | WebSocket `/ws` 长连接对话 |
| `mcp_agent/server/mcp_host.py` | 自举 MCP Server（把 Agent 暴露为 MCP 工具） |

## 扩展点

- **新增 LLM 厂商**：在 `config.LLM_PROVIDERS` 增加一个 OpenAI 兼容模板即可；
- **新增多模态能力**：在 `capabilities/` 实现对应 Provider 协议并注册（如新版 TTS、语音克隆、视频模型、真渲染数字人）；
- **长期记忆 / RAG**：实现 `mcp_agent/core/memory.py` 的 `Memory` 协议并注入 `AgentRuntime`；
- **自定义工具**：优先实现为独立 MCP Server（语言无关、可独立部署）；进程内工具用 `LocalToolKit`。

## 开源协议

[MIT](LICENSE)。
