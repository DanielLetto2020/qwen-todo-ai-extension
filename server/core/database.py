import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from core.config import DATABASE_PATH, get_board_name_for_request, set_board_name


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Инициализация БД + миграция."""
    with get_db() as conn:
        # 1. Создаём таблицу boards
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Создаём таблицу notes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL,
                title VARCHAR(100) NOT NULL,
                body TEXT DEFAULT '',
                color VARCHAR(20) DEFAULT 'blue',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE CASCADE
            )
        """)

        # 3. Создаём columns и tasks
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS columns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(50) NOT NULL,
                status_code INTEGER NOT NULL,
                color VARCHAR(20) NOT NULL DEFAULT '#3B82F6',
                board VARCHAR(100) NOT NULL DEFAULT 'main',
                UNIQUE(status_code, board)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_task INTEGER NOT NULL,
                title VARCHAR(100) NOT NULL,
                description TEXT DEFAULT '',
                context_ai TEXT DEFAULT '',
                status INTEGER NOT NULL DEFAULT 0,
                type VARCHAR(50) DEFAULT 'base',
                priority INTEGER NOT NULL DEFAULT 0,
                log TEXT DEFAULT '[]',
                ai_notepad TEXT DEFAULT '',
                checklist TEXT DEFAULT '{}',
                board VARCHAR(100) NOT NULL DEFAULT 'main',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(id_task, board)
            );
        """)

        # Миграция: если колонки board нет в tasks — добавляем
        try:
            conn.execute("SELECT board FROM tasks LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE tasks ADD COLUMN board VARCHAR(100) NOT NULL DEFAULT 'main'")
            conn.execute("UPDATE tasks SET board = 'main' WHERE board IS NULL")

        # Миграция: если колонки board нет в columns — пересоздаём таблицу
        try:
            conn.execute("SELECT board FROM columns LIMIT 1")
        except sqlite3.OperationalError:
            existing = conn.execute("SELECT id, name, status_code, color FROM columns").fetchall()
            conn.execute("DROP TABLE columns")
            conn.execute("""
                CREATE TABLE columns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(50) NOT NULL,
                    status_code INTEGER NOT NULL,
                    color VARCHAR(20) NOT NULL DEFAULT '#3B82F6',
                    board VARCHAR(100) NOT NULL DEFAULT 'main',
                    UNIQUE(status_code, board)
                )
            """)
            for row in existing:
                conn.execute(
                    "INSERT INTO columns (id, name, status_code, color, board) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], row["name"], row["status_code"], row["color"], "main")
                )

        # Миграция: если UNIQUE не на (status_code, board) — пересоздаём
        try:
            conn.execute("INSERT INTO columns (status_code, board) VALUES (0, '__test__')")
            conn.execute("DELETE FROM columns WHERE board = '__test__'")
        except sqlite3.IntegrityError:
            existing = conn.execute("SELECT id, name, status_code, color, board FROM columns").fetchall()
            conn.execute("DROP TABLE columns")
            conn.execute("""
                CREATE TABLE columns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(50) NOT NULL,
                    status_code INTEGER NOT NULL,
                    color VARCHAR(20) NOT NULL DEFAULT '#3B82F6',
                    board VARCHAR(100) NOT NULL DEFAULT 'main',
                    UNIQUE(status_code, board)
                )
            """)
            for row in existing:
                conn.execute(
                    "INSERT INTO columns (id, name, status_code, color, board) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], row["name"], row["status_code"], row["color"], row["board"])
                )

        # 4. Миграция: создаём доску 'main' если её нет
        conn.execute("INSERT OR IGNORE INTO boards (name) VALUES ('main')")

        # 5. Миграция: создаём доски из существующих tasks/columns
        existing_boards = conn.execute(
            "SELECT DISTINCT board FROM tasks UNION SELECT DISTINCT board FROM columns"
        ).fetchall()
        for row in existing_boards:
            conn.execute("INSERT OR IGNORE INTO boards (name) VALUES (?)", (row["board"],))

        # Вставляем колонки доски для доски 'main' (дефолт)
        # Для других досок колонки создаются при переключении через init_columns_for_board
        for name, code, color in [
            ('Бэклог', 0, '#3B82F6'),
            ('Бэклог-AI', 1, '#8B5CF6'),
            ('Сделать', 2, '#F59E0B'),
            ('В работе', 3, '#10B981'),
            ('Требует внимания', 4, '#EF4444'),
            ('Готово', 5, '#06B6D4'),
            ('Архив', 6, '#6B7280'),
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO columns (name, status_code, color, board) VALUES (?, ?, ?, ?)",
                (name, code, color, "main")
            )


def row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if "checklist" in d and isinstance(d["checklist"], str):
        cl = parse_checklist(d["checklist"])
        d["checklist"] = cl
        d["checklist_title"] = cl.get("title", "")
    # Для UI: api_id = id_task (бизнес-ID), чтобы фронтенд использовал его для API-вызовов
    if "id_task" in d:
        d["api_id"] = d["id_task"]
    return d


def parse_checklist(json_str: str) -> dict:
    try:
        data = json.loads(json_str) if json_str and json_str != '{}' else {}
    except Exception:
        data = {}
    if "title" not in data:
        data["title"] = ""
    if "tasks" not in data:
        data["tasks"] = []
    return data


def append_to_log(log_json: str, action: str, creator: str, details: str = "") -> str:
    log = json.loads(log_json) if log_json else []
    log.append({
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "creator": creator,
        "details": details,
    })
    return json.dumps(log, ensure_ascii=False)


def validate_status_creator(status: int, creator: str):
    if status == 0 and creator != "human":
        raise HTTPException(403, "Только человек может создавать задачи в Бэклог (status=0)")
    if status == 1 and creator != "ai":
        raise HTTPException(403, "Только AI может создавать задачи в Бэклог-AI (status=1)")


def get_next_task_id(board: str = None) -> int:
    """Получить следующий id_task для конкретной доски."""
    if board is None:
        from core.config import get_board_name
        board = get_board_name()
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id_task), 0) as max_id FROM tasks WHERE board = ?",
            (board,)
        ).fetchone()
        return row["max_id"] + 1


def get_all_boards() -> list:
    """Получить список всех досок из таблицы boards."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT b.name, 
                      (SELECT COUNT(*) FROM tasks t WHERE t.board = b.name) as task_count
               FROM boards b ORDER BY b.name"""
        ).fetchall()
        return [{"name": r["name"], "task_count": r["task_count"]} for r in rows]


def get_board_id(board_name: str) -> Optional[int]:
    """Получить ID доски по имени."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM boards WHERE name = ?", (board_name,)).fetchone()
        return row["id"] if row else None


def delete_board(board_name: str) -> int:
    """Удалить доску и все связанные данные."""
    with get_db() as conn:
        board_id = get_board_id(board_name)
        if not board_id:
            return 0
        task_count = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE board = ?", (board_name,)).fetchone()["cnt"]
        note_count = conn.execute("SELECT COUNT(*) as cnt FROM notes WHERE board_id = ?", (board_id,)).fetchone()["cnt"]
        conn.execute("DELETE FROM tasks WHERE board = ?", (board_name,))
        conn.execute("DELETE FROM columns WHERE board = ?", (board_name,))
        conn.execute("DELETE FROM notes WHERE board_id = ?", (board_id,))
        conn.execute("DELETE FROM boards WHERE id = ?", (board_id,))
    return task_count + note_count


def init_columns_for_board(board_name: str):
    """Создать доску и колонки для неё."""
    with get_db() as conn:
        # Создаём доску
        conn.execute("INSERT OR IGNORE INTO boards (name) VALUES (?)", (board_name,))
        # Создаём колонки
        for name, code, color in [
            ('Бэклог', 0, '#3B82F6'),
            ('Бэклог-AI', 1, '#8B5CF6'),
            ('Сделать', 2, '#F59E0B'),
            ('В работе', 3, '#10B981'),
            ('Требует внимания', 4, '#EF4444'),
            ('Готово', 5, '#06B6D4'),
            ('Архив', 6, '#6B7280'),
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO columns (name, status_code, color, board) VALUES (?, ?, ?, ?)",
                (name, code, color, board_name)
            )
