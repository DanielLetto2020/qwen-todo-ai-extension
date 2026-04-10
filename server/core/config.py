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

# Определяем дополнительный путь для поиска конфига проекта
# Если WORKSPACE_PATH установлен Qwen Code, но не указывает на реальный проект,
# попробуем использовать PROJECT_PATH из env (если установлен) или найдём конфиг динамически
PROJECT_PATH = os.environ.get("PROJECT_PATH", None)


def _find_project_config_path() -> str:
    """Найти путь к .qwen/todo-ai.json, поднимаясь от текущей директории."""
    # Сначала пробуем PROJECT_PATH если установлен
    if PROJECT_PATH:
        config_path = os.path.join(PROJECT_PATH, ".qwen", "todo-ai.json")
        if os.path.exists(config_path):
            return PROJECT_PATH

    # Затем пробуем текущую рабочую директорию процесса
    cwd = os.getcwd()
    config_path = os.path.join(cwd, ".qwen", "todo-ai.json")
    if os.path.exists(config_path):
        return cwd

    # Поднимаемся на 2 уровня вверх ищем конфиг
    current = cwd
    for _ in range(5):
        config_path = os.path.join(current, ".qwen", "todo-ai.json")
        if os.path.exists(config_path):
            return current
        parent = os.path.dirname(current)
        if parent == current:  # Достигли корня
            break
        current = parent

    return None


def get_board_name() -> str:
    """Определить имя доски: из .qwen/todo-ai.json проекта или дефолт 'main'."""
    # Сначала ищем конфиг в PROJECT_PATH или текущей директории
    project_dir = _find_project_config_path()
    if project_dir:
        config_path = os.path.join(project_dir, ".qwen", "todo-ai.json")
        try:
            with open(config_path) as f:
                config = json.load(f)
                board = config.get("board", "main")
                return board if board else "main"
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: читаем из WORKSPACE_PATH (старое поведение)
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
