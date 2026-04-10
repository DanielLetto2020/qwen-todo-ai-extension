import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

from core.database import (
    get_db,
    row_to_dict,
    append_to_log,
    validate_status_creator,
)
from core.models import MCPToolCall, TaskCreate, TaskUpdate
from core.tasks_api import create_task, update_task, get_task, _list_tasks_internal, delete_task
from core.ws_manager import manager, broadcast_task_change
from core.config import get_board_name_for_request

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

MCP_TOOLS = [
    {
        "name": "create_task",
        "description": "Создать задачу в колонке Бэклог-AI (status=1). Только для AI-агентов.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок задачи (до 100 символов)"},
                "description": {"type": "string", "description": "Описание задачи (до 10000 символов)"},
                "context_ai": {"type": "string", "description": "Стартовый контекст для AI"},
                "checklist": {"type": "object", "description": "Чеклист задачи: {\"title\": \"...\", \"tasks\": [...]}"},
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
                "title": {"type": "string", "description": "Новый заголовок"},
                "description": {"type": "string", "description": "Новое описание"},
                "context_ai": {"type": "string", "description": "Обновлённый контекст AI"},
                "status": {"type": "integer", "description": "Новый статус (0-6)"},
                "type": {"type": "string", "description": "Новый тип задачи"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_task",
        "description": "Получить задачу по ID. Задача должна принадлежать текущей доске.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID задачи"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Получить список задач с фильтрами (только текущая доска).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "integer", "description": "Фильтр по статусу (0-6)"},
            },
        },
    },
    {
        "name": "delete_task",
        "description": "Удалить задачу по ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID задачи"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "write_to_notepad",
        "description": "Записать заметку в AI-блок задачи (ai_notepad).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "ID задачи"},
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
                "task_id": {"type": "integer", "description": "ID задачи"},
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
                "task_id": {"type": "integer", "description": "ID задачи"},
                "status": {"type": "integer", "description": "Новый статус (0-6)"},
            },
            "required": ["task_id", "status"],
        },
    },
    {
        "name": "todo_next",
        "description": "Показать следующую задачу из колонки 'Сделать' (status=2). Только просмотр, без изменения статуса.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "todo_next_run",
        "description": "Взять следующую задачу из 'Сделать' (status=2) и переместить в 'В работе' (status=3).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "todo_list",
        "description": "Показать задачи из колонки 'Бэклог-AI' (status=1). Возвращает до 50 задач с кратким описанием.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Максимум задач", "default": 50},
            },
        },
    },
]


@router.get("/tools", summary="Список MCP инструментов")
def mcp_list_tools():
    return {
        "tools": MCP_TOOLS,
        "server": "todo-ai-orchestrator",
        "version": "1.0.0",
        "board": get_board_name_for_request(),
    }


@router.get("/docs", summary="Документация MCP (Markdown)")
def mcp_docs():
    return {
        "docs": """# MCP Documentation — todo-ai-orchestrator

## Overview
MCP (Model Context Protocol) позволяет AI-агентам взаимодействовать с Kanban-доской.

## Base URL
http://localhost:8167/api

## Available Tools
create_task, update_task, get_task, list_tasks, delete_task, write_to_notepad, append_log, change_status, todo_next, todo_next_run, todo_list

## Status Codes
0=Бэклог(human), 1=Бэклог-AI(ai), 2=Сделать, 3=В работе, 4=Требует внимания, 5=Готово, 6=Архив

## Task Schema
id, id_task, title, description, context_ai, status, type, priority, log, ai_notepad, checklist, board, created_at, updated_at

## Правила
- Только creator=human может создавать задачи в status=0 (Бэклог)
- Только creator=ai может создавать задачи в status=1 (Бэклог-AI)
- Все изменения логируются автоматически
- Каждая задача привязана к доске (board)
"""
    }


@router.post("/tools/call", summary="Вызов MCP инструмента")
async def mcp_call_tool(tool_call: MCPToolCall):
    name = tool_call.name
    args = tool_call.arguments

    try:
        match name:
            case "create_task":
                task = TaskCreate(
                    title=args["title"],
                    description=args.get("description", ""),
                    context_ai=args.get("context_ai", ""),
                    status=1,
                    type=args.get("type", "base"),
                    checklist=args.get("checklist", {}),
                    creator="ai",
                )
                result = create_task(task)
                await manager.broadcast({"type": "task_change", "action": "task_created", "result": result})
                return result

            case "update_task":
                task_id = args.pop("task_id")
                update_fields = TaskUpdate(**args, creator="ai")
                return update_task(task_id, update_fields)

            case "get_task":
                return get_task(args["task_id"])

            case "list_tasks":
                return _list_tasks_internal(status=args.get("status"))

            case "delete_task":
                task_id = args["task_id"]
                result = delete_task(task_id)
                await manager.broadcast({"type": "task_change", "action": "task_deleted", "task_id": task_id})
                return result

            case "write_to_notepad":
                task_id = args["task_id"]
                note = args["note"]
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
                        (task_id, get_board_name_for_request())
                    ).fetchone()
                    if not row:
                        raise HTTPException(404, "Задача не найдена")
                    new_notepad = (row["ai_notepad"] or "") + "\n" + note
                    now = datetime.utcnow().isoformat()
                    new_log = append_to_log(row["log"], "notepad_updated", "ai", note)
                    conn.execute(
                        "UPDATE tasks SET ai_notepad = ?, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (new_notepad.strip(), now, new_log, task_id, get_board_name_for_request())
                    )
                return {"message": "Заметка добавлена"}

            case "append_log":
                task_id = args["task_id"]
                log_entry_text = args["log_entry"]
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
                        (task_id, get_board_name_for_request())
                    ).fetchone()
                    if not row:
                        raise HTTPException(404, "Задача не найдена")
                    new_log = append_to_log(row["log"], "ai_log", "ai", log_entry_text)
                    now = datetime.utcnow().isoformat()
                    conn.execute(
                        "UPDATE tasks SET updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (now, new_log, task_id, get_board_name_for_request())
                    )
                return {"message": "Запись в лог добавлена"}

            case "change_status":
                task_id = args["task_id"]
                new_status = args["status"]
                validate_status_creator(new_status, "ai")
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
                        (task_id, get_board_name_for_request())
                    ).fetchone()
                    if not row:
                        raise HTTPException(404, "Задача не найдена")
                    now = datetime.utcnow().isoformat()
                    new_log = append_to_log(row["log"], "status_changed", "ai", f"Статус: {row['status']} -> {new_status}")
                    conn.execute(
                        "UPDATE tasks SET status = ?, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (new_status, now, new_log, task_id, get_board_name_for_request())
                    )
                    updated = row_to_dict(conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?", (task_id, get_board_name_for_request())
                    ).fetchone())
                await broadcast_task_change(task_id, updated, "status_changed")
                return {"message": "Статус изменён", "old_status": row["status"], "new_status": new_status}

            case "todo_next":
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE status = 2 AND board = ? ORDER BY priority ASC, id_task ASC LIMIT 1",
                        (get_board_name_for_request(),)
                    ).fetchone()
                if not row:
                    return {"message": "Нет задач в колонке 'Сделать'", "task": None}
                task = row_to_dict(row)
                return {"message": f"Следующая задача: #{task['id_task']} {task['title']}", "task": task}

            case "todo_next_run":
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE status = 2 AND board = ? ORDER BY priority ASC, id_task ASC LIMIT 1",
                        (get_board_name_for_request(),)
                    ).fetchone()
                    if not row:
                        return {"message": "Нет задач в колонке 'Сделать'", "task": None}
                    task = row_to_dict(row)
                    task_id = task["id_task"]
                    now = datetime.utcnow().isoformat()
                    new_log = append_to_log(task["log"], "status_changed", "ai", "Статус: 2 -> 3 (В работе)")
                    conn.execute(
                        "UPDATE tasks SET status = 3, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
                        (now, new_log, task_id, get_board_name_for_request())
                    )
                    updated = row_to_dict(conn.execute(
                        "SELECT * FROM tasks WHERE id_task = ? AND board = ?", (task_id, get_board_name_for_request())
                    ).fetchone())
                await broadcast_task_change(task_id, updated, "status_changed")
                return {"message": f"Задача #{task['id_task']} '{task['title']}' взята в выполнение", "task": updated}

            case "todo_list":
                limit = args.get("limit", 50)
                with get_db() as conn:
                    rows = conn.execute(
                        "SELECT id_task, title, description, context_ai, priority, created_at FROM tasks WHERE status = 1 AND board = ? ORDER BY priority ASC, id_task ASC LIMIT ?",
                        (get_board_name_for_request(), limit)
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
                raise HTTPException(400, f"Неизвестный инструмент: {name}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Ошибка вызова MCP: {str(e)}")
