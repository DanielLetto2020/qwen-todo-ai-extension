import os
import json

# Путь к БД (из env или дефолт)
DATABASE_PATH = os.environ.get("DATABASE_URL", "").replace("sqlite:///", "")
if not DATABASE_PATH:
    ext_path = os.environ.get("EXTENSION_PATH", os.path.expanduser("~/.qwen/extensions/todo-ai"))
    DATABASE_PATH = os.path.join(ext_path, "data", "tasks.db")

os.makedirs(os.path.dirname(DATABASE_PATH) if os.path.dirname(DATABASE_PATH) else ".", exist_ok=True)

# Путь к workspace (из env — для stdio режима)
WORKSPACE_PATH = os.environ.get("WORKSPACE_PATH", os.getcwd())


def get_board_name() -> str:
    """Определить имя доски: из .qwen/todo-ai.json workspace или дефолт 'main'."""
    config_path = os.path.join(WORKSPACE_PATH, ".qwen", "todo-ai.json")
    try:
        with open(config_path) as f:
            config = json.load(f)
            board = config.get("board", "main")
            return board if board else "main"
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return "main"


def get_board_name_for_request() -> str:
    """Динамически определяет board — для HTTP режима (читает конфиг при каждом запросе)."""
    return get_board_name()


def set_board_name(board: str) -> str:
    """Записать имя доски в .qwen/todo-ai.json."""
    config_dir = os.path.join(WORKSPACE_PATH, ".qwen")
    config_path = os.path.join(config_dir, "todo-ai.json")
    os.makedirs(config_dir, exist_ok=True)
    try:
        with open(config_path) as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    config["board"] = board
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    return board

def get_default_port() -> int:
    """Получить порт по умолчанию: из env TODO_AI_APP_PORT или 8167."""
    return int(os.environ.get("TODO_AI_APP_PORT", 8167))


# Режим работы: stdio (MCP) или http (UI + API)
SERVER_MODE = os.environ.get("SERVER_MODE", "http")

# Путь к config-app.json
CONFIG_PATH = os.environ.get("CONFIG_PATH", "")
if not CONFIG_PATH:
    ext_path = os.environ.get("EXTENSION_PATH", os.path.expanduser("~/.qwen/extensions/todo-ai"))
    CONFIG_PATH = os.path.join(ext_path, "server", "config-app.json")
