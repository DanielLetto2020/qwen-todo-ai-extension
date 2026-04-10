"""API для просмотра SQLite базы данных (read-only)."""
from fastapi import APIRouter, HTTPException

from core.database import get_db

router = APIRouter(prefix="/api/db", tags=["db"])


@router.get("/tables", summary="Список всех таблиц (кроме системных)")
def list_tables():
    with get_db() as conn:
        # Исключаем sqlite_* и таблицы миграций
        rows = conn.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' 
               AND name NOT LIKE 'sqlite_%'
               ORDER BY name"""
        ).fetchall()
        tables = []
        for r in rows:
            count = conn.execute(f'SELECT COUNT(*) as cnt FROM "{r["name"]}"').fetchone()["cnt"]
            tables.append({"name": r["name"], "row_count": count})
    return {"tables": tables}


@router.get("/table/{table_name}", summary="Содержимое таблицы")
def get_table(table_name: str):
    with get_db() as conn:
        # Проверка что таблица существует и не системная
        exists = conn.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' AND name = ? 
               AND name NOT LIKE 'sqlite_%'""", (table_name,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, f"Таблица '{table_name}' не найдена")

        # Получаем колонки и данные
        cursor = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 500')
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    return {"table": table_name, "columns": columns, "rows": rows}
