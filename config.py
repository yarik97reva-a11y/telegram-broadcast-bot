import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота (получить у @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID первого администратора (ваш Telegram ID)
# Получить можно у @userinfobot
FIRST_ADMIN_ID = int(os.getenv("FIRST_ADMIN_ID", "0"))

# Путь к базе данных
DATABASE_PATH = os.getenv("DATABASE_PATH", "broadcast_bot.db")

# Часовой пояс
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
