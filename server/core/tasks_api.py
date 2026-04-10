import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Body

from core.database import (
    get_db,
    row_to_dict,
    append_to_log,
    validate_status_creator,
    get_next_task_id,
)
from core.models import TaskCreate, TaskUpdate, TaskStatusChange, TaskReorder
from core.ws_manager import manager, broadcast_task_change
from core.config import get_board_name_for_request

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _list_tasks_internal(
    status: Optional[int] = None,
    order_by: str = "priority",
):
    """Внутренняя функция — вызывается из API и MCP."""
    order_clause = "priority ASC, id_task ASC" if order_by == "priority" else "id_task ASC"
    with get_db() as conn:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? AND board = ? ORDER BY " + order_clause,
                (status, get_board_name_for_request()),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE board = ? ORDER BY " + order_clause,
                (get_board_name_for_request(),)
            ).fetchall()
    return [row_to_dict(r) for r in rows]


@router.get("", summary="Получить все задачи")
def list_tasks_api(
    status: Optional[int] = Query(None, ge=0, le=6),
    order_by: str = Query("priority"),
):
    """FastAPI endpoint — вызывает внутреннюю функцию."""
    return _list_tasks_internal(status=status, order_by=order_by)


@router.get("/{task_id}", summary="Получить задачу по ID")
def get_task(task_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
            (task_id, get_board_name_for_request())
        ).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")
    return row_to_dict(row)


@router.post("", status_code=201, summary="Создать задачу")
def create_task(task: TaskCreate):
    validate_status_creator(task.status, task.creator)
    task_id = get_next_task_id(get_board_name_for_request())
    now = datetime.utcnow().isoformat()
    log_entry = json.dumps([{
        "timestamp": now,
        "action": "created",
        "creator": task.creator,
        "details": f"Создана задача #{task_id}",
    }], ensure_ascii=False)

    with get_db() as conn:
        conn.execute(
            """INSERT INTO tasks (id_task, title, description, context_ai, status, type, checklist, log, ai_notepad, board, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, task.title, task.description, task.context_ai,
             task.status, task.type, json.dumps(task.checklist, ensure_ascii=False),
             log_entry, "", get_board_name_for_request(), now, now)
        )
    return {"message": "Задача создана", "task_id": task_id, "id_task": task_id}


@router.put("/{task_id}", summary="Обновить задачу")
def update_task(task_id: int, task: TaskUpdate):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
            (task_id, get_board_name_for_request())
        ).fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")

        if task.status is not None:
            validate_status_creator(task.status, task.creator)

        fields = []
        values = []
        updated_field_names = []
        now = datetime.utcnow().isoformat()

        for key, val in task.model_dump(exclude_none=True).items():
            if key == "creator":
                continue
            fields.append(f"{key} = ?")
            if key == "checklist":
                values.append(json.dumps(val, ensure_ascii=False))
            else:
                values.append(val)
            if key != "updated_at":
                updated_field_names.append(key)

        if not fields:
            return {"message": "Нет полей для обновления"}

        fields.append("updated_at = ?")
        values.append(now)

        if updated_field_names:
            new_log = append_to_log(row["log"], "updated", task.creator, f"Обновлены: {', '.join(updated_field_names)}")
        fields.append("log = ?")
        values.append(new_log)

        values.append(task_id)
        conn.execute(
            "UPDATE tasks SET " + ", ".join(fields) + " WHERE id_task = ? AND board = ?",
            values + [get_board_name_for_request()]
        )
    return {"message": "Задача обновлена"}


@router.patch("/{task_id}/status", summary="Изменить статус (drag-and-drop)")
def change_status(task_id: int, change: TaskStatusChange, background_tasks: BackgroundTasks):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
            (task_id, get_board_name_for_request())
        ).fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")

        validate_status_creator(change.status, change.creator)

        now = datetime.utcnow().isoformat()
        new_log = append_to_log(
            row["log"], "status_changed", change.creator,
            f"Статус: {row['status']} → {change.status}"
        )

        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
            (change.status, now, new_log, task_id, get_board_name_for_request())
        )
        updated = row_to_dict(conn.execute(
            "SELECT * FROM tasks WHERE id_task = ? AND board = ?", (task_id, get_board_name_for_request())
        ).fetchone())

    background_tasks.add_task(broadcast_task_change, task_id, updated, "status_changed")
    return {"message": "Статус изменён", "old_status": row["status"], "new_status": change.status}


@router.delete("/{task_id}", summary="Удалить задачу")
def delete_task(task_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
            (task_id, get_board_name_for_request())
        ).fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")
        conn.execute("DELETE FROM tasks WHERE id_task = ? AND board = ?", (task_id, get_board_name_for_request()))
    return {"message": "Задача удалена"}


@router.patch("/{task_id}/reorder", summary="Изменить приоритет задачи")
def reorder_task(task_id: int, reorder: TaskReorder):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
            (task_id, get_board_name_for_request())
        ).fetchone()
        if not row:
            raise HTTPException(404, "Задача не найдена")
        now = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE tasks SET priority = ?, updated_at = ? WHERE id_task = ? AND board = ?",
            (reorder.priority, now, task_id, get_board_name_for_request())
        )
    return {"message": "Приоритет обновлён", "priority": reorder.priority}


# ═══════════════════════════════════════════════════════
# Checklist API — работа с вложенным чеклистом в задаче
# ═══════════════════════════════════════════════════════

def _get_checklist(conn, task_id: int) -> tuple:
    """Возвращает (task_row, checklist_dict)."""
    row = conn.execute(
        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
        (task_id, get_board_name_for_request())
    ).fetchone()
    if not row:
        raise HTTPException(404, "Задача не найдена")
    cl = json.loads(row["checklist"]) if row["checklist"] and row["checklist"] != "{}" else {}
    if "title" not in cl:
        cl["title"] = ""
    if "tasks" not in cl:
        cl["tasks"] = []
    return row, cl


def _save_checklist(conn, task_id: int, checklist: dict, log_action: str = "checklist_updated"):
    """Сохраняет чеклист и логирует изменение."""
    row = conn.execute(
        "SELECT * FROM tasks WHERE id_task = ? AND board = ?",
        (task_id, get_board_name_for_request())
    ).fetchone()
    now = datetime.utcnow().isoformat()
    new_log = append_to_log(row["log"], log_action, "human", f"Чеклист: {checklist.get('title', '')}")
    conn.execute(
        "UPDATE tasks SET checklist = ?, updated_at = ?, log = ? WHERE id_task = ? AND board = ?",
        (json.dumps(checklist, ensure_ascii=False), now, new_log, task_id, get_board_name_for_request())
    )


def _flatten_with_depth(items: list, depth: int = 0) -> list:
    result = []
    for item in items:
        if isinstance(item, str):
            item = {"id": str(uuid.uuid4())[:8], "title": item, "done": False, "children": []}
        flat_item = {
            "id": item.get("id", str(uuid.uuid4())[:8]),
            "title": item.get("title", ""),
            "done": item.get("done", False),
            "depth": depth,
            "children": _flatten_with_depth(item.get("children", []), depth + 1),
        }
        result.append(flat_item)
    return result


def _find_and_remove(items: list, item_id: str) -> bool:
    for i, item in enumerate(items):
        if item.get("id") == item_id:
            items.pop(i)
            return True
        if item.get("children"):
            if _find_and_remove(item["children"], item_id):
                return True
    return False


def _find_and_update(items: list, item_id: str, updates: dict) -> bool:
    for item in items:
        if item.get("id") == item_id:
            item.update(updates)
            return True
        if item.get("children"):
            if _find_and_update(item["children"], item_id, updates):
                return True
    return False


def _find_parent_and_add(items: list, parent_id: str | None, new_item: dict) -> bool:
    if parent_id is None:
        items.append(new_item)
        return True
    for item in items:
        if item.get("id") == parent_id:
            if "children" not in item:
                item["children"] = []
            item["children"].append(new_item)
            return True
        if item.get("children"):
            if _find_parent_and_add(item["children"], parent_id, new_item):
                return True
    return False


def _count_items(items: list) -> int:
    total = 0
    for item in items:
        total += 1
        if item.get("children"):
            total += _count_items(item["children"])
    return total


@router.get("/{task_id}/checklist", summary="Получить чеклист задачи")
def get_task_checklist(task_id: int):
    with get_db() as conn:
        row, cl = _get_checklist(conn, task_id)
    return {
        "checklist_title": cl.get("title", ""),
        "items": _flatten_with_depth(cl.get("tasks", [])),
    }


@router.post("/{task_id}/checklist/title", summary="Создать или переименовать чеклист")
def set_checklist_title(task_id: int, body: dict = Body(...)):
    checklist_title = body.get("checklist_title", "").strip()
    if not checklist_title:
        raise HTTPException(400, "checklist_title обязателен")
    with get_db() as conn:
        row, cl = _get_checklist(conn, task_id)
        cl["title"] = checklist_title
        _save_checklist(conn, task_id, cl, "checklist_title_set")
    return {"message": "Заголовок чеклиста установлен", "checklist_title": checklist_title}


@router.post("/{task_id}/checklist", summary="Добавить пункт в чеклист", status_code=201)
def add_checklist_item(task_id: int, body: dict = Body(...)):
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(400, "title обязателен")
    parent_id = body.get("parent_id")

    with get_db() as conn:
        row, cl = _get_checklist(conn, task_id)

    max_depth = 0

    def get_max_depth(items, depth=0):
        nonlocal max_depth
        for item in items:
            max_depth = max(max_depth, depth)
            if item.get("children"):
                get_max_depth(item["children"], depth + 1)

    get_max_depth(cl.get("tasks", []))
    if parent_id:
        def find_depth(items, target_id, depth=0):
            for item in items:
                if item.get("id") == target_id:
                    return depth
                if item.get("children"):
                    r = find_depth(item["children"], target_id, depth + 1)
                    if r is not None:
                        return r
            return None

        parent_depth = find_depth(cl.get("tasks", []), str(parent_id))
        if parent_depth is not None and parent_depth >= 4:
            raise HTTPException(400, "Максимальная глубина чеклиста — 5 уровней (0-4)")

    new_item = {
        "id": str(uuid.uuid4())[:8],
        "title": title,
        "done": False,
        "children": [],
    }

    if not _find_parent_and_add(cl.get("tasks", []), str(parent_id) if parent_id else None, new_item):
        raise HTTPException(400, "Родитель не найден")

    with get_db() as conn:
        _save_checklist(conn, task_id, cl, "checklist_item_added")
    return {"message": "Пункт добавлен", "item_id": new_item["id"]}


@router.patch("/{task_id}/checklist/{item_id}", summary="Отметить/снять пункт чеклиста")
def toggle_checklist_item(task_id: int, item_id: str, body: dict = Body(...)):
    done = body.get("done", False)
    with get_db() as conn:
        row, cl = _get_checklist(conn, task_id)
        if not _find_and_update(cl.get("tasks", []), item_id, {"done": done}):
            raise HTTPException(404, "Пункт не найден")
        _save_checklist(conn, task_id, cl, "checklist_item_toggled")
    return {"message": "Пункт обновлён", "item_id": item_id, "done": done}


@router.delete("/{task_id}/checklist/{item_id}", summary="Удалить пункт чеклиста")
def delete_checklist_item(task_id: int, item_id: str):
    with get_db() as conn:
        row, cl = _get_checklist(conn, task_id)
        if not _find_and_remove(cl.get("tasks", []), item_id):
            raise HTTPException(404, "Пункт не найден")
        _save_checklist(conn, task_id, cl, "checklist_item_deleted")
    return {"message": "Пункт удалён", "item_id": item_id}


@router.delete("/{task_id}/checklist/all", summary="Удалить весь чеклист")
def delete_checklist_all(task_id: int):
    with get_db() as conn:
        row, cl = _get_checklist(conn, task_id)
        cl["title"] = ""
        cl["tasks"] = []
        _save_checklist(conn, task_id, cl, "checklist_cleared")
    return {"message": "Чеклист удалён"}
