"""API для заметок, привязанных к доскам."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Body

from core.database import get_db, get_board_name_for_request, get_board_id

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", summary="Список заметок текущей доски")
def list_notes():
    board = get_board_name_for_request()
    board_id = get_board_id(board)
    if not board_id:
        return {"notes": []}
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, board_id, title, body, color, created_at, updated_at 
               FROM notes WHERE board_id = ? ORDER BY updated_at DESC""",
            (board_id,)
        ).fetchall()
        return {"notes": [dict(r) for r in rows]}


@router.post("", status_code=201, summary="Создать заметку")
def create_note(body: dict = Body(...)):
    board = get_board_name_for_request()
    board_id = get_board_id(board)
    if not board_id:
        raise HTTPException(404, "Доска не найдена")
    
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(400, "Заголовок обязателен")
    
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO notes (board_id, title, body, color, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (board_id, title, body.get("body", ""), body.get("color", "blue"), now, now)
        )
        note_id = cursor.lastrowid
        note = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return {"note": dict(note)}


@router.put("/{note_id}", summary="Обновить заметку")
def update_note(note_id: int, body: dict = Body(...)):
    board = get_board_name_for_request()
    board_id = get_board_id(board)
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM notes WHERE id = ? AND board_id = ?", (note_id, board_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Заметка не найдена")
        
        now = datetime.utcnow().isoformat()
        conn.execute(
            """UPDATE notes SET title = ?, body = ?, color = ?, updated_at = ? WHERE id = ?""",
            (body.get("title", row["title"]), body.get("body", row["body"]),
             body.get("color", row["color"]), now, note_id)
        )
        updated = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return {"note": dict(updated)}


@router.delete("/{note_id}", summary="Удалить заметку")
def delete_note(note_id: int):
    board = get_board_name_for_request()
    board_id = get_board_id(board)
    
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM notes WHERE id = ? AND board_id = ?", (note_id, board_id)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Заметка не найдена")
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return {"message": "Заметка удалена"}
