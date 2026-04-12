"""
Модуль проверки и автозапуска UI сервера.
Используется MCP сервером при старте сессии.
"""
import os
import sys
import subprocess
import socket
import time
import logging

logger = logging.getLogger(__name__)

# Порт по умолчанию
DEFAULT_PORT = int(os.environ.get("TODO_AI_APP_PORT", 8167))


def is_port_in_use(port: int = DEFAULT_PORT) -> bool:
    """Проверить, занят ли порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return False
        except OSError:
            return True


def is_ui_running(port: int = DEFAULT_PORT) -> bool:
    """Проверить, работает ли UI сервер на указанном порту."""
    import urllib.request
    try:
        url = f"http://127.0.0.1:{port}/health"
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def start_ui_server(port: int = DEFAULT_PORT, background: bool = True) -> subprocess.Popen | None:
    """
    Запустить UI сервер как независимый процесс.
    
    Args:
        port: Порт для запуска
        background: True для запуска как независимого процесса (daemon)
    
    Returns:
        Popen объект или None если ошибка
    """
    # Определяем путь к расширению
    ext_path = os.environ.get("EXTENSION_PATH", 
                              os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Формируем команду запуска
    cmd = [
        sys.executable,  # python
        "-m", "server.main",
        "--port", str(port)
    ]
    
    # Окружение для HTTP режима
    env = os.environ.copy()
    env["SERVER_MODE"] = "http"
    env["EXTENSION_PATH"] = ext_path
    env["DATABASE_URL"] = f"sqlite://{ext_path}/data/tasks.db"
    env["CONFIG_PATH"] = os.path.join(ext_path, "server", "config-app.json")
    
    try:
        if background:
            # Запускаем как независимый процесс (не subprocess)
            # Используем start_new_session для Linux/Mac
            if sys.platform in ('linux', 'darwin'):
                process = subprocess.Popen(
                    cmd,
                    cwd=ext_path,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True  # Отделяем от родительского процесса
                )
            else:
                # Windows
                process = subprocess.Popen(
                    cmd,
                    cwd=ext_path,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            
            logger.info(f"UI сервер запущен на порту {port}, PID: {process.pid}")
            return process
        else:
            # Синхронный запуск (для отладки)
            process = subprocess.Popen(
                cmd,
                cwd=ext_path,
                env=env
            )
            return process
            
    except Exception as e:
        logger.error(f"Ошибка запуска UI сервера: {e}")
        return None


def ensure_ui_running(port: int = DEFAULT_PORT, max_retries: int = 3) -> bool:
    """
    Проверить и при необходимости запустить UI сервер.
    
    Args:
        port: Порт для проверки/запуска
        max_retries: Количество попыток проверки после запуска
    
    Returns:
        True если UI работает, False если ошибка
    """
    # Шаг 1: Проверяем работает ли уже
    if is_ui_running(port):
        logger.info(f"UI сервер уже работает на порту {port}")
        return True
    
    # Шаг 2: Если порт занят но UI не отвечает — ждём освобождения (TIME_WAIT)
    if is_port_in_use(port):
        logger.warning(f"Порт {port} занят, ожидание освобождения...")
        import time
        for wait_attempt in range(5):
            time.sleep(1)
            if not is_port_in_use(port):
                logger.info(f"Порт {port} освободился после {wait_attempt + 1}с")
                break
            if is_ui_running(port):
                logger.info(f"UI сервер запустился на порту {port}")
                return True
        else:
            # Порт всё ещё занят через 5 секунд
            if is_ui_running(port):
                return True
            logger.error(f"Порт {port} остаётся занятым, UI не отвечает")
            return False
    
    # Шаг 3: Запускаем UI сервер
    logger.info(f"Запуск UI сервера на порту {port}...")
    process = start_ui_server(port, background=True)
    
    if not process:
        logger.error("Не удалось запустить UI сервер")
        return False
    
    # Шаг 4: Ждём запуска и проверяем
    import time
    for attempt in range(max_retries):
        time.sleep(1)
        if is_ui_running(port):
            logger.info(f"UI сервер успешно запущен на порту {port} (попытка {attempt + 1})")
            return True
    
    logger.warning(f"UI сервер не ответил после {max_retries} попыток")
    return False


def get_ui_url(port: int = DEFAULT_PORT) -> str:
    """Получить URL UI сервера."""
    return f"http://127.0.0.1:{port}"
