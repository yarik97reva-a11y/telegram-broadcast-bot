import os
from pathlib import Path

# Пытаемся загрузить .env если он существует (для локальной разработки)
# На сервере (Render, Railway) используются переменные окружения напрямую
try:
    from dotenv import load_dotenv
    env_path = Path('.') / '.env'
    if env_path.exists():
        load_dotenv()
except ImportError:
    pass  # dotenv не установлен или .env не существует, используем системные переменные

# Токен бота (получить у @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID первого администратора (ваш Telegram ID)
# Получить можно у @userinfobot
FIRST_ADMIN_ID = int(os.getenv("FIRST_ADMIN_ID", "0"))

# Путь к базе данных
DATABASE_PATH = os.getenv("DATABASE_PATH", "broadcast_bot.db")

# Часовой пояс
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
