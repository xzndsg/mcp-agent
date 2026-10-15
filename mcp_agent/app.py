"""Flask 应用工厂：组装内核、注册蓝图 / WebSocket / 控制台。"""
from __future__ import annotations

import threading

from flask import Flask, render_template

from .core.config import AppConfig
from .core.logging_utils import get_logger
from .server.context import build_container
from .server.gateway_api import bp as gateway_bp
from .server.mcp_admin_api import bp as admin_bp
from .server.responses import register_error_handlers
from .server.rest_api import bp as rest_bp
from .server.ws_api import init_websocket

logger = get_logger("app")


def create_app(config: AppConfig | None = None, start_background: bool = True) -> Flask:
    app = Flask(
        __name__,
        template_folder="server/web/templates",
        static_folder="server/web/static",
        static_url_path="/static",
    )
    app.config["JSON_AS_ASCII"] = False

    container = build_container(config)
    app.extensions["mcp_agent"] = container

    # 轻量 CORS（不引额外依赖）；生产可按需收紧来源
    @app.after_request
    def _cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    app.register_blueprint(rest_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(gateway_bp)
    init_websocket(app, container)
    register_error_handlers(app)

    @app.get("/")
    def index():
        return render_template("index.html")

    if start_background:
        def _bootstrap() -> None:
            if container.config.autostart:
                container.manager.autostart_all()
            container.manager.start_health_check()

        threading.Thread(target=_bootstrap, name="mcp-bootstrap", daemon=True).start()

    return app
