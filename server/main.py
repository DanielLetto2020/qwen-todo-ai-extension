"""todo-ai-orchestrator v2.0.0 — Extension Edition"""
import sys
import os
import json
import asyncio
from datetime import datetime

# Добавляем корень расширения И server/ в sys.path
ext_path = os.environ.get("EXTENSION_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
server_path = os.path.join(ext_path, "server")
for p in [ext_path, server_path]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Импортируем config ПЕРВЫМ — он определяет доску из .qwen/todo-ai.json
from core.config import SERVER_MODE, WORKSPACE_PATH, get_board_name, get_default_port
from core.database import init_db, get_db, row_to_dict, append_to_log, validate_status_creator, get_next_task_id


# ═══════════════════════════════════════════════════════
# STDIO MCP режим — JSON-RPC через stdin/stdout
# ═══════════════════════════════════════════════════════

def get_mcp_tools_def():
    """Определения MCP инструментов (для stdio режима)."""
    return [
        {
            "name": "create_task",
            "description": "Создать задачу в колонке Бэклог-AI (status=1). Только для AI-агентов.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Заголовок задачи (до 100 символов)"},
                    "description": {"type": "string", "description": "Описание задачи (до 10000 символов)"},
                    "context_ai": {"type": "string", "description": "Стартовый контекст для AI"},
                    "checklist": {"type": "object", "description": "Чеклист: {\"title\": \"...\", \"tasks\": [...]}"},
                },
                "required": ["title"],
            },
        },
        {
            "name": "update_task",
            "description": "Обновить поля существующей задачи.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "ID задачи (id_task)"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "context_ai": {"type": "string"},
                    "status": {"type": "integer", "description": "Новый статус (0-6)"},
                    "type": {"type": "string"},
                },
                "required": ["task_id"],
            },
        },
        {
            "name": "get_task",
            "description": "Получить задачу по ID.",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "integer", "description": "ID задачи"}},
                "required": ["task_id"],
            },
        },
        {
            "name": "list_tasks",
            "description": "Получить список задач с фильтрами (только текущая доска).",
            "inputSchema": {
                "type": "object",
                "properties": {"status": {"type": "integer", "description": "Фильтр по статусу (0-6)"}},
            },
        },
        {
            "name": "delete_task",
            "description": "Удалить задачу по ID.",
            "inputSchema": {
                "type": "object",
                "properties": {"task_id": {"type": "integer", "description": "ID задачи"}},
                "required": ["task_id"],
            },
        },
        {
            "name": "write_to_notepad",
            "description": "Записать заметку в AI-блок задачи (ai_notepad).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "note": {"type": "string", "description": "Текст заметки"},
                },
                "required": ["task_id", "note"],
            },
        },
        {
            "name": "append_log",
            "description": "Добавить запись в лог истории задачи.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "log_entry": {"type": "string", "description": "Текст записи в лог"},
                },
                "required": ["task_id", "log_entry"],
            },
        },
        {
            "name": "change_status",
            "description": "Изменить статус задачи (переместить в другую колонку).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "status": {"type": "integer", "description": "Новый статус (0-6)"},
                },
                "required": ["task_id", "status"],
            },
        },
        {
            "name": "todo_next",
            "description": "Показать следующую задачу из колонки 'Сделать' (status=2). Только просмотр.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "todo_next_run",
            "description": "Взять следующую задачу из 'Сделать' (status=2) → 'В работе' (status=3).",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "todo_list",
            "description": "Показать задачи из 'Бэклог-AI' (status=1). До 50 задач.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 50}},
            },
        },
    ]


def handle_tool_call(name: str, arguments: dict) -> dict:
    """Вызов MCP инструмента (синхронно, для stdio)."""
    try:
        match name:
            case "create_task":
                board = get_board_name()
                task_id = get_next_task_id(board)
                now = datetime.utcnow().isoformat()
                log_entry = json.dumps([{
                    "timestamp": now, "action": "created", "creator": "ai",
                    "details": f"Создана задача #{task_id}",
                }], ensure_ascii=False)
                checklist_json = json.dumps(arguments.get("checklist", {}), ensure_ascii=False)
                with get_db() as conn:
                    conn.execute(
                        """INSERT INTO tasks (id_task, title, description, context_ai, status, type, checklist, log, ai_notepad, board, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (task_id, arguments["title"], arguments.get("description", ""),
                         arguments.get("context_ai", ""), 1, arguments.get("type", "base"),
                         checklist_json, log_entry, "", board, now, now)
                    )
                return {"message": "Задача создана", "task_id": task_id, "id_task": task_id}

            case "update_task":
                task_id = arguments.pop("task_id")
                from core.models import TaskUpdate
                from core.tasks_api import update_task as api_update
                return api_update(task_id, TaskUpdate(**arguments, creator="ai"))

            case "get_task":
                from core.tasks_api import get_task as api_get
                return api_get(arguments["task_id"])

            case "list_tasks":
                from core.tasks_api import _list_tasks_internal
                return _list_tasks_internal(status=arguments.get("status"))

            case "delete_task":
                from core.tasks_api import delete_task as api_delete
                return api_delete(arguments["task_id"])

            case "write_to_notepad":
                task_id = arguments["task_id"]
                note = arguments["note"]
                board = get_board_name()
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
                        (task_id, board)
                    ).fetchone()
                    if not row:
                        return {"error": "Задача не найдена"}
                    new_notepad = (row["ai_notepad"] or "") + "\n" + note
                    now = datetime.utcnow().isoformat()
                    new_log = append_to_log(row["log"], "notepad_updated", "ai", note)
                    conn.execute(
                        "UPDATE tasks SET ai_notepad = ?, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (new_notepad.strip(), now, new_log, task_id, board)
                    )
                return {"message": "Заметка добавлена"}

            case "append_log":
                task_id = arguments["task_id"]
                log_entry_text = arguments["log_entry"]
                board = get_board_name()
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
                        (task_id, board)
                    ).fetchone()
                    if not row:
                        return {"error": "Задача не найдена"}
                    new_log = append_to_log(row["log"], "ai_log", "ai", log_entry_text)
                    now = datetime.utcnow().isoformat()
                    conn.execute(
                        "UPDATE tasks SET updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (now, new_log, task_id, board)
                    )
                return {"message": "Запись в лог добавлена"}

            case "change_status":
                task_id = arguments["task_id"]
                new_status = arguments["status"]
                validate_status_creator(new_status, "ai")
                board = get_board_name()
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
                        (task_id, board)
                    ).fetchone()
                    if not row:
                        return {"error": "Задача не найдена"}
                    now = datetime.utcnow().isoformat()
                    new_log = append_to_log(row["log"], "status_changed", "ai", f"Статус: {row['status']} -> {new_status}")
                    conn.execute(
                        "UPDATE tasks SET status = ?, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (new_status, now, new_log, task_id, board)
                    )
                return {"message": "Статус изменён", "old_status": row["status"], "new_status": new_status}

            case "todo_next":
                board = get_board_name()
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE status = 2 AND board = ? ORDER BY priority ASC, id_task ASC LIMIT 1",
                        (board,)
                    ).fetchone()
                if not row:
                    return {"message": "Нет задач в колонке 'Сделать'", "task": None}
                task = row_to_dict(row)
                return {"message": f"Следующая задача: #{task['id_task']} {task['title']}", "task": task}

            case "todo_next_run":
                board = get_board_name()
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE status = 2 AND board = ? ORDER BY priority ASC, id_task ASC LIMIT 1",
                        (board,)
                    ).fetchone()
                    if not row:
                        return {"message": "Нет задач в колонке 'Сделать'", "task": None}
                    task = row_to_dict(row)
                    task_id = task["id_task"]
                    now = datetime.utcnow().isoformat()
                    new_log = append_to_log(task["log"], "status_changed", "ai", "Статус: 2 -> 3 (В работе)")
                    conn.execute(
                        "UPDATE tasks SET status = 3, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (now, new_log, task_id, board)
                    )
                    updated = row_to_dict(conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?", (task_id, board)
                    ).fetchone())
                return {"message": f"Задача #{task['id_task']} '{task['title']}' взята в выполнение", "task": updated}

            case "todo_list":
                limit = arguments.get("limit", 50)
                board = get_board_name()
                with get_db() as conn:
                    rows = conn.execute(
                        "SELECT id_task, title, description, context_ai, priority, created_at FROM tasks WHERE status = 1 AND board = ? ORDER BY priority ASC, id_task ASC LIMIT ?",
                        (board, limit)
                    ).fetchall()
                tasks = []
                for r in rows:
                    d = dict(r)
                    if d["description"] and len(d["description"]) > 50:
                        d["description_short"] = d["description"][:50] + "..."
                    else:
                        d["description_short"] = d["description"]
                    tasks.append(d)
                return {"message": f"Найдено задач в 'Бэклог-AI': {len(tasks)}", "tasks": tasks}

            case _:
                return {"error": f"Неизвестный инструмент: {name}"}

    except Exception as e:
        return {"error": str(e)}


async def run_stdio_mcp():
    """JSON-RPC сервер через stdin/stdout."""
    init_db()
    board = get_board_name()
    # Отправляем initialization ответ
    print(json.dumps({"jsonrpc": "2.0", "method": "initialize", "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "todo-ai", "version": "1.0.0", "board": board}
    }}, ensure_ascii=False), flush=True)

    loop = asyncio.get_event_loop()

    def read_line():
        try:
            return sys.stdin.readline()
        except Exception:
            return None

    while True:
        line = await loop.run_in_executor(None, read_line)
        if not line:
            break

        try:
            request = json.loads(line.strip())
            method = request.get("method", "")
            params = request.get("params", {})
            req_id = request.get("id")

            if method == "tools/list":
                result = {"tools": get_mcp_tools_def()}
                if req_id is not None:
                    resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
                    print(json.dumps(resp, ensure_ascii=False), flush=True)

            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                tool_result = handle_tool_call(tool_name, tool_args)
                content = [{"type": "text", "text": json.dumps(tool_result, ensure_ascii=False, default=str)}]
                if req_id is not None:
                    resp = {"jsonrpc": "2.0", "id": req_id, "result": {"content": content, "isError": "error" in tool_result}}
                    print(json.dumps(resp, ensure_ascii=False), flush=True)

            elif method == "initialize":
                if req_id is not None:
                    resp = {"jsonrpc": "2.0", "id": req_id, "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "todo-ai", "version": "1.0.0", "board": get_board_name()}
                    }}
                    print(json.dumps(resp, ensure_ascii=False), flush=True)

            elif method == "initialized":
                pass

            elif req_id is not None:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
                print(json.dumps(resp, ensure_ascii=False), flush=True)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            try:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}
                print(json.dumps(resp, ensure_ascii=False), flush=True)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════
# HTTP режим — FastAPI с UI
# ═══════════════════════════════════════════════════════
def run_http(port: int = 8167):
    """Запуск FastAPI сервера с UI и MCP API."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from core.routes import router as routes_router
    from core.tasks_api import router as tasks_router
    from core.mcp_handler import router as mcp_router
    from core.boards_api import router as boards_router
    from core.db_api import router as db_router
    from core.notes_api import router as notes_router

    app = FastAPI(
        title="todo-ai-orchestrator",
        description="Kanban-доска с MCP API для AI-агентов.",
        version="1.0.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_router)
    app.include_router(tasks_router)
    app.include_router(mcp_router)
    app.include_router(boards_router)
    app.include_router(db_router)
    app.include_router(notes_router)

    @app.on_event("startup")
    def startup():
        init_db()

    uvicorn.run(app, host="0.0.0.0", port=port)


# ═══════════════════════════════════════════════════════
# Главная точка входа
# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse

    # Загрузка .env файла если существует
    env_path = os.path.join(ext_path, ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

    parser = argparse.ArgumentParser(description="Todo AI — Kanban-доска для AI-агентов")
    parser.add_argument("--port", type=int, default=get_default_port(),
                        help="Порт для HTTP UI (по умолч. 8167, или env TODO_AI_APP_PORT)")
    args = parser.parse_args()

    mode = os.environ.get("SERVER_MODE", "stdio")
    if mode == "stdio":
        asyncio.run(run_stdio_mcp())
    else:
        run_http(port=args.port)
