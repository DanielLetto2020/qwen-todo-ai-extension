import os
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket
from fastapi.responses import HTMLResponse, FileResponse

from core.ws_manager import websocket_endpoint
from core.database import get_db, row_to_dict
from core.config import CONFIG_PATH, get_board_name_for_request

router = APIRouter(tags=["routes"])


@router.get("/api/board", summary="Получить колонки и задачи")
def get_board():
    board = get_board_name_for_request()
    with get_db() as conn:
        columns = conn.execute(
            "SELECT * FROM columns WHERE board = ? ORDER BY status_code",
            (board,)
        ).fetchall()
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE board = ? ORDER BY id_task",
            (board,)
        ).fetchall()
    return {
        "columns": [row_to_dict(c) for c in columns],
        "tasks": [row_to_dict(t) for t in tasks],
        "board": board,
    }


def _get_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"version": "unknown"}


@router.get("/config", summary="Конфигурация приложения")
def get_config():
    return _get_config()


@router.get("/health", summary="Health check")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "board": get_board_name_for_request()}


@router.get("/task-types", summary="Доступные типы задач и их конфигурация")
def get_task_types():
    return {
        "types": {
            "base": {
                "name": "Base",
                "description": "Базовый тип задачи",
                "fields": ["title", "description", "context_ai", "status", "type", "log", "ai_notepad", "checklist"],
                "permissions": {
                    "can_edit_title": True,
                    "can_edit_description": True,
                    "can_edit_context_ai": True,
                    "can_change_status": True,
                },
            },
        },
        "note": "Чеклист хранится как JSON: {\"title\": \"...\", \"tasks\": [{\"title\": \"...\", \"done\": false, \"children\": [...]}]}"
    }


@router.get("/", include_in_schema=False)
def serve_frontend():
    # Ищем static/index.html относительно server/ директории
    base_dir = os.path.dirname(os.path.dirname(__file__))
    index_path = os.path.join(base_dir, "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>todo-ai-orchestrator</h1><p>index.html not found</p>")


@router.get("/favicon.svg", include_in_schema=False)
def serve_favicon():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    favicon_path = os.path.join(base_dir, "static", "favicon.svg")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/svg+xml")
    return HTMLResponse("")


@router.get("/app-docs", include_in_schema=False)
def serve_app_docs():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    docs_path = os.path.join(base_dir, "static", "docs.html")
    if os.path.exists(docs_path):
        return FileResponse(docs_path)
    return HTMLResponse("<h1>Docs not found</h1>")


@router.get("/mcp-tools", include_in_schema=False)
def serve_mcp_tools():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    mcp_path = os.path.join(base_dir, "static", "mcp.html")
    if os.path.exists(mcp_path):
        return FileResponse(mcp_path)
    return HTMLResponse("<h1>MCP Tools not found</h1>")


@router.get("/notes", include_in_schema=False)
def serve_notes():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    notes_path = os.path.join(base_dir, "static", "notes.html")
    if os.path.exists(notes_path):
        return FileResponse(notes_path)
    return HTMLResponse("<h1>Notes page not found</h1>")


@router.get("/changelog", include_in_schema=False)
def serve_changelog():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    changelog_path = os.path.join(base_dir, "static", "changelog.html")
    if os.path.exists(changelog_path):
        return FileResponse(changelog_path)
    return HTMLResponse("<h1>Changelog page not found</h1>")


@router.get("/docs-app", include_in_schema=False)
def serve_docs_app():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    docs_path = os.path.join(base_dir, "static", "docs-app.html")
    if os.path.exists(docs_path):
        return FileResponse(docs_path)
    return HTMLResponse("<h1>Documentation page not found</h1>")


@router.get("/db", include_in_schema=False)
def serve_db():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, "static", "db.html")
    if os.path.exists(db_path):
        return FileResponse(db_path)
    return HTMLResponse("<h1>DB Viewer page not found</h1>")


@router.get("/settings", include_in_schema=False)
def serve_settings():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    settings_path = os.path.join(base_dir, "static", "settings.html")
    if os.path.exists(settings_path):
        return FileResponse(settings_path)
    return HTMLResponse("<h1>Settings page not found</h1>")


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket_endpoint(websocket)
