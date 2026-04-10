"""API для управления мультидосками."""
import re

from fastapi import APIRouter, HTTPException, Body

from core.database import (
    get_db, get_all_boards, delete_board, init_columns_for_board,
    get_board_name_for_request, set_board_name, get_board_id
)

router = APIRouter(prefix="/api/boards", tags=["boards"])


def _validate_board_name(name: str) -> str:
    """Проверить имя доски: только буквы, цифры, дефис, подчёркивание."""
    name = name.strip()
    if not name:
        raise HTTPException(400, "Имя доски не может быть пустым")
    if len(name) > 50:
        raise HTTPException(400, "Имя доски слишком длинное (макс. 50 символов)")
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        raise HTTPException(400, "Имя доски может содержать только буквы, цифры, дефис и подчёркивание")
    return name


@router.get("", summary="Список всех досок")
def list_boards():
    boards_data = get_all_boards()
    active = get_board_name_for_request()
    result = []
    for b in boards_data:
        result.append({
            "name": b["name"],
            "task_count": b["task_count"],
            "is_active": b["name"] == active,
        })
    return {"boards": result, "active": active}


@router.get("/active", summary="Текущая активная доска")
def get_active_board():
    return {"board": get_board_name_for_request()}


@router.put("/active", summary="Переключить активную доску")
def set_active_board(body: dict = Body(...)):
    board_name = _validate_board_name(body.get("board", ""))
    # Если доски ещё нет — создаём
    existing = [b["name"] for b in get_all_boards()]
    if board_name not in existing:
        init_columns_for_board(board_name)
    set_board_name(board_name)
    return {"message": f"Активная доска: {board_name}", "board": board_name}


@router.post("", status_code=201, summary="Создать новую доску")
def create_board(body: dict = Body(...)):
    board_name = _validate_board_name(body.get("name", ""))
    if board_name == "main":
        raise HTTPException(400, "Доска 'main' уже существует и является системной")
    existing = [b["name"] for b in get_all_boards()]
    if board_name in existing:
        raise HTTPException(409, f"Доска '{board_name}' уже существует")
    init_columns_for_board(board_name)
    set_board_name(board_name)
    return {"message": f"Доска '{board_name}' создана", "board": board_name}


@router.delete("/{board_name}", summary="Удалить доску")
def delete_board_api(board_name: str):
    board_name = _validate_board_name(board_name)
    if board_name == "main":
        raise HTTPException(400, "Доска 'main' является системной и не может быть удалена")
    existing = [b["name"] for b in get_all_boards()]
    if board_name not in existing:
        raise HTTPException(404, f"Доска '{board_name}' не найдена")
    if len(existing) <= 1:
        raise HTTPException(400, "Нельзя удалить последнюю доску")
    deleted = delete_board(board_name)
    return {"message": f"Доска '{board_name}' удалена ({deleted} записей)", "records_deleted": deleted}
