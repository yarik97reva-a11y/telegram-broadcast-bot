import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from database import Database
from scheduler import BroadcastScheduler
import config

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(BROADCAST_TITLE, BROADCAST_TEXT, BROADCAST_CHATS,
 BROADCAST_TIME, BROADCAST_FREQUENCY, BROADCAST_REPEAT,
 BROADCAST_GENDER, BROADCAST_AGE_MIN, BROADCAST_AGE_MAX,
 ADD_CHAT_ID, ADD_CHAT_NAME,
 REGISTER_GENDER, REGISTER_AGE,
 ADD_ADMIN_ID) = range(14)

# Глобальные объекты
db = Database(config.DATABASE_PATH)
scheduler = None


def admin_only(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not db.is_admin(user_id):
            await update.message.reply_text(
                "❌ У вас нет прав для выполнения этой команды."
            )
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


def owner_only(func):
    """Декоратор для проверки прав главного администратора"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not db.is_owner(user_id):
            if update.callback_query:
                await update.callback_query.answer(
                    "❌ Только главный администратор может выполнять это действие!",
                    show_alert=True
                )
            else:
                await update.message.reply_text(
                    "❌ Только главный администратор может выполнять это действие!"
                )
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    username = update.effective_user.username

    # Добавляем первого админа как owner (главный администратор)
    if user_id == config.FIRST_ADMIN_ID and not db.is_admin(user_id):
        db.add_admin(user_id, username, role='owner')
        logger.info(f"Added first admin (owner): {user_id}")

    if not db.is_admin(user_id):
        await update.message.reply_text(
            "❌ Доступ запрещен. Этот бот только для администраторов."
        )
        return

    await show_main_menu(update, context)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображение главного меню"""
    user_id = update.effective_user.id
    is_owner = db.is_owner(user_id)

    keyboard = [
        [InlineKeyboardButton("📤 Создать рассылку", callback_data="create_broadcast")],
        [InlineKeyboardButton("📋 Мои рассылки", callback_data="list_broadcasts")],
        [InlineKeyboardButton("👥 Управление чатами", callback_data="manage_chats")],
    ]

    # Кнопка "Администраторы" видна только главному администратору
    if is_owner:
        keyboard.append([InlineKeyboardButton("👨‍💼 Администраторы", callback_data="manage_admins")])

    keyboard.extend([
        [InlineKeyboardButton("📊 Статистика", callback_data="statistics")],
        [InlineKeyboardButton("👤 Пользователи", callback_data="user_stats")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "🤖 <b>Бот для массовых рассылок</b>\n\n"
        "Выберите действие из меню ниже:"
    )

    if update.callback_query:
        await update.callback_query.message.edit_text(
            text, reply_markup=reply_markup, parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=reply_markup, parse_mode="HTML"
        )


# === СОЗДАНИЕ РАССЫЛКИ ===
@admin_only
async def create_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания рассылки"""
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "📝 <b>Создание новой рассылки</b>\n\n"
        "Шаг 1/6: Введите название рассылки (для вашего удобства):",
        parse_mode="HTML"
    )
    return BROADCAST_TITLE


async def broadcast_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия рассылки"""
    context.user_data['broadcast_title'] = update.message.text

    await update.message.reply_text(
        "Шаг 2/6: Введите текст рассылки:\n\n"
        "Вы можете использовать HTML-форматирование:\n"
        "<b>жирный</b>, <i>курсив</i>, <code>код</code>"
    )
    return BROADCAST_TEXT


async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение текста рассылки"""
    context.user_data['broadcast_text'] = update.message.text

    # Показываем доступные чаты
    chats = db.get_target_chats(active_only=True)
    if not chats:
        await update.message.reply_text(
            "❌ У вас нет активных чатов для рассылки.\n"
            "Сначала добавьте чаты через меню 'Управление чатами'."
        )
        return ConversationHandler.END

    keyboard = []
    for chat in chats:
        keyboard.append([
            InlineKeyboardButton(
                f"✅ {chat['chat_name']}",
                callback_data=f"toggle_chat_{chat['chat_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("➡️ Далее", callback_data="chats_selected")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    context.user_data['selected_chats'] = [chat['chat_id'] for chat in chats]

    await update.message.reply_text(
        "Шаг 3/6: Выберите чаты для рассылки:\n"
        "(Нажмите на чат, чтобы исключить его из рассылки)",
        reply_markup=reply_markup
    )
    return BROADCAST_CHATS


async def toggle_chat_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение выбора чата"""
    query = update.callback_query
    await query.answer()

    chat_id = query.data.replace("toggle_chat_", "")
    selected = context.user_data.get('selected_chats', [])

    if chat_id in selected:
        selected.remove(chat_id)
        status = "❌"
    else:
        selected.append(chat_id)
        status = "✅"

    context.user_data['selected_chats'] = selected

    # Обновляем кнопки
    chats = db.get_target_chats(active_only=True)
    keyboard = []
    for chat in chats:
        mark = "✅" if chat['chat_id'] in selected else "❌"
        keyboard.append([
            InlineKeyboardButton(
                f"{mark} {chat['chat_name']}",
                callback_data=f"toggle_chat_{chat['chat_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("➡️ Далее", callback_data="chats_selected")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_reply_markup(reply_markup=reply_markup)
    return BROADCAST_CHATS


async def chats_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение выбора чатов"""
    query = update.callback_query
    await query.answer()

    if not context.user_data.get('selected_chats'):
        await query.message.reply_text("❌ Выберите хотя бы один чат!")
        return BROADCAST_CHATS

    keyboard = [
        [InlineKeyboardButton("⏰ Через 5 минут", callback_data="time_5min")],
        [InlineKeyboardButton("🕐 Через 1 час", callback_data="time_1hour")],
        [InlineKeyboardButton("📅 Завтра в это время", callback_data="time_tomorrow")],
        [InlineKeyboardButton("✏️ Указать время вручную", callback_data="time_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        "Шаг 4/6: Когда начать рассылку?",
        reply_markup=reply_markup
    )
    return BROADCAST_TIME


async def broadcast_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка времени рассылки"""
    query = update.callback_query
    await query.answer()

    time_option = query.data.replace("time_", "")
    now = datetime.now()

    if time_option == "5min":
        scheduled_time = now + timedelta(minutes=5)
    elif time_option == "1hour":
        scheduled_time = now + timedelta(hours=1)
    elif time_option == "tomorrow":
        scheduled_time = now + timedelta(days=1)
    elif time_option == "custom":
        await query.message.reply_text(
            "Введите дату и время в формате:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Например: <code>25.12.2024 15:30</code>",
            parse_mode="HTML"
        )
        return BROADCAST_TIME

    context.user_data['scheduled_time'] = scheduled_time

    keyboard = [
        [InlineKeyboardButton("1️⃣ Один раз", callback_data="freq_once")],
        [InlineKeyboardButton("⏰ Каждый час", callback_data="freq_hourly")],
        [InlineKeyboardButton("📅 Каждый день", callback_data="freq_daily")],
        [InlineKeyboardButton("📆 Каждую неделю", callback_data="freq_weekly")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        f"✅ Время установлено: {scheduled_time.strftime('%d.%m.%Y %H:%M')}\n\n"
        "Шаг 5/6: Выберите частоту рассылки:",
        reply_markup=reply_markup
    )
    return BROADCAST_FREQUENCY


async def broadcast_time_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ручного ввода времени"""
    try:
        time_str = update.message.text
        scheduled_time = datetime.strptime(time_str, "%d.%m.%Y %H:%M")

        if scheduled_time < datetime.now():
            await update.message.reply_text(
                "❌ Указанное время уже прошло. Введите будущее время."
            )
            return BROADCAST_TIME

        context.user_data['scheduled_time'] = scheduled_time

        keyboard = [
            [InlineKeyboardButton("1️⃣ Один раз", callback_data="freq_once")],
            [InlineKeyboardButton("⏰ Каждый час", callback_data="freq_hourly")],
            [InlineKeyboardButton("📅 Каждый день", callback_data="freq_daily")],
            [InlineKeyboardButton("📆 Каждую неделю", callback_data="freq_weekly")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"✅ Время установлено: {scheduled_time.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Шаг 5/6: Выберите частоту рассылки:",
            reply_markup=reply_markup
        )
        return BROADCAST_FREQUENCY

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат времени. Используйте:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
            parse_mode="HTML"
        )
        return BROADCAST_TIME


async def broadcast_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка частоты рассылки"""
    query = update.callback_query
    await query.answer()

    freq_map = {
        "freq_once": "once",
        "freq_hourly": "hourly",
        "freq_daily": "daily",
        "freq_weekly": "weekly"
    }
    frequency = freq_map[query.data]
    context.user_data['frequency'] = frequency

    if frequency == "once":
        context.user_data['repeat_count'] = 1
    else:
        await query.message.reply_text(
            "Шаг 6: Сколько раз повторить рассылку?\n"
            "Введите число (например: 5)"
        )
        return BROADCAST_REPEAT

    # Переходим к выбору фильтров
    await ask_gender_filter(update, context)
    return BROADCAST_GENDER


async def broadcast_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка количества повторов"""
    try:
        repeat_count = int(update.message.text)
        if repeat_count < 1:
            raise ValueError

        context.user_data['repeat_count'] = repeat_count

        # Переходим к выбору фильтров
        await ask_gender_filter(update, context)
        return BROADCAST_GENDER

    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число (больше 0)"
        )
        return BROADCAST_REPEAT


async def ask_gender_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос фильтра по полу"""
    keyboard = [
        [InlineKeyboardButton("👥 Всем", callback_data="gender_all")],
        [InlineKeyboardButton("👨 Только мужчинам", callback_data="gender_male")],
        [InlineKeyboardButton("👩 Только женщинам", callback_data="gender_female")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "Шаг 7: Фильтр по полу\n\nКому отправить рассылку?"

    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def broadcast_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора пола"""
    query = update.callback_query
    await query.answer()

    gender_map = {
        "gender_all": None,
        "gender_male": "male",
        "gender_female": "female"
    }
    context.user_data['gender_filter'] = gender_map[query.data]

    # Переходим к возрасту
    keyboard = [
        [InlineKeyboardButton("👶 Всем возрастам", callback_data="age_all")],
        [InlineKeyboardButton("🎯 Указать возраст", callback_data="age_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        "Шаг 8: Фильтр по возрасту\n\nВыберите возрастную группу:",
        reply_markup=reply_markup
    )
    return BROADCAST_AGE_MIN


async def broadcast_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора возраста"""
    query = update.callback_query
    await query.answer()

    if query.data == "age_all":
        context.user_data['age_min'] = None
        context.user_data['age_max'] = None
        await save_broadcast(update, context)
        return ConversationHandler.END
    else:
        await query.message.reply_text(
            "Укажите минимальный возраст (например: 18)\n"
            "Или напишите 0, если без ограничения:"
        )
        return BROADCAST_AGE_MIN


async def broadcast_age_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка минимального возраста"""
    try:
        age_min = int(update.message.text)
        if age_min < 0:
            raise ValueError

        context.user_data['age_min'] = age_min if age_min > 0 else None

        await update.message.reply_text(
            "Укажите максимальный возраст (например: 45)\n"
            "Или напишите 0, если без ограничения:"
        )
        return BROADCAST_AGE_MAX

    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число (от 0)"
        )
        return BROADCAST_AGE_MIN


async def broadcast_age_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка максимального возраста"""
    try:
        age_max = int(update.message.text)
        if age_max < 0:
            raise ValueError

        context.user_data['age_max'] = age_max if age_max > 0 else None

        # Проверка логики
        age_min = context.user_data.get('age_min')
        if age_min and age_max and age_max < age_min:
            await update.message.reply_text(
                "❌ Максимальный возраст не может быть меньше минимального!\n"
                "Попробуйте снова:"
            )
            return BROADCAST_AGE_MAX

        await save_broadcast(update, context)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число (от 0)"
        )
        return BROADCAST_AGE_MAX


async def save_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение рассылки и запуск"""
    try:
        broadcast_id = db.create_broadcast(
            title=context.user_data['broadcast_title'],
            message_text=context.user_data['broadcast_text'],
            target_chats=context.user_data['selected_chats'],
            scheduled_time=context.user_data['scheduled_time'],
            frequency=context.user_data['frequency'],
            repeat_count=context.user_data.get('repeat_count', 1),
            gender_filter=context.user_data.get('gender_filter'),
            age_min=context.user_data.get('age_min'),
            age_max=context.user_data.get('age_max')
        )

        # Планируем рассылку
        scheduler.schedule_broadcast(broadcast_id)

        freq_text = {
            "once": "один раз",
            "hourly": "каждый час",
            "daily": "каждый день",
            "weekly": "каждую неделю"
        }

        gender_text = {
            None: "всем",
            "male": "мужчинам",
            "female": "женщинам"
        }

        text = (
            "✅ <b>Рассылка создана!</b>\n\n"
            f"📝 Название: {context.user_data['broadcast_title']}\n"
            f"⏰ Время: {context.user_data['scheduled_time'].strftime('%d.%m.%Y %H:%M')}\n"
            f"🔄 Частота: {freq_text[context.user_data['frequency']]}\n"
            f"🎯 Чатов: {len(context.user_data['selected_chats'])}\n"
        )

        # Добавляем информацию о фильтрах
        gender_filter = context.user_data.get('gender_filter')
        age_min = context.user_data.get('age_min')
        age_max = context.user_data.get('age_max')

        if gender_filter or age_min or age_max:
            text += f"👥 Фильтр: {gender_text.get(gender_filter, 'всем')}"
            if age_min or age_max:
                age_range = f", возраст "
                if age_min and age_max:
                    age_range += f"{age_min}-{age_max}"
                elif age_min:
                    age_range += f"от {age_min}"
                elif age_max:
                    age_range += f"до {age_max}"
                text += age_range
            text += "\n"

        text += f"🔢 ID: {broadcast_id}"

        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")

        # Очищаем данные
        context.user_data.clear()

    except Exception as e:
        logger.error(f"Error saving broadcast: {e}")
        error_text = "❌ Ошибка при создании рассылки. Попробуйте снова."
        if update.callback_query:
            await update.callback_query.message.reply_text(error_text)
        else:
            await update.message.reply_text(error_text)


# === СПИСОК РАССЫЛОК ===
async def list_broadcasts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать список рассылок"""
    query = update.callback_query
    await query.answer()

    broadcasts = db.get_broadcasts()

    if not broadcasts:
        await query.message.reply_text(
            "📋 У вас пока нет рассылок.\n"
            "Создайте первую через меню!"
        )
        await show_main_menu(update, context)
        return

    text = "📋 <b>Ваши рассылки:</b>\n\n"
    keyboard = []

    for bc in broadcasts:
        status_emoji = {
            "pending": "⏳",
            "active": "✅",
            "completed": "✔️",
            "failed": "❌"
        }
        emoji = status_emoji.get(bc['status'], "❓")

        text += (
            f"{emoji} <b>{bc['title']}</b>\n"
            f"   ID: {bc['id']} | {bc['status']}\n"
            f"   {bc['scheduled_time']}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {bc['title'][:20]}...",
                callback_data=f"view_broadcast_{bc['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def view_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр деталей рассылки"""
    query = update.callback_query
    await query.answer()

    broadcast_id = int(query.data.replace("view_broadcast_", ""))
    broadcast = db.get_broadcast(broadcast_id)

    if not broadcast:
        await query.message.reply_text("❌ Рассылка не найдена")
        return

    stats = db.get_broadcast_stats(broadcast_id)

    text = (
        f"📊 <b>Рассылка: {broadcast['title']}</b>\n\n"
        f"🆔 ID: {broadcast['id']}\n"
        f"📅 Время: {broadcast['scheduled_time']}\n"
        f"🔄 Частота: {broadcast['frequency']}\n"
        f"🎯 Чатов: {len(broadcast['target_chats'])}\n"
        f"📈 Статус: {broadcast['status']}\n"
        f"🔢 Повторов: {broadcast['current_repeat']}/{broadcast['repeat_count']}\n\n"
        f"📤 Отправлено: {stats['total_sent']}\n"
        f"✅ Доставлено: {stats['delivered']}\n"
        f"👀 Просмотров: {stats['total_views']}\n"
        f"🖱 Кликов: {stats['total_clicks']}\n\n"
        f"💬 <b>Текст:</b>\n{broadcast['message_text']}"
    )

    keyboard = [
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_broadcast_{broadcast_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="list_broadcasts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def delete_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление рассылки"""
    query = update.callback_query
    await query.answer()

    broadcast_id = int(query.data.replace("delete_broadcast_", ""))

    # Отменяем запланированную задачу
    scheduler.cancel_broadcast(broadcast_id)

    # Удаляем из БД
    db.delete_broadcast(broadcast_id)

    await query.message.reply_text("✅ Рассылка удалена")
    await list_broadcasts(update, context)


# === УПРАВЛЕНИЕ ЧАТАМИ ===
async def manage_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление целевыми чатами"""
    query = update.callback_query
    await query.answer()

    chats = db.get_target_chats(active_only=False)

    keyboard = []
    text = "👥 <b>Управление чатами</b>\n\n"

    if chats:
        text += "Ваши чаты:\n\n"
        for chat in chats:
            status = "✅" if chat['is_active'] else "❌"
            text += f"{status} {chat['chat_name']} ({chat['chat_id']})\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {chat['chat_name'][:25]}",
                    callback_data=f"edit_chat_{chat['chat_id']}"
                )
            ])
    else:
        text += "У вас пока нет добавленных чатов.\n"

    keyboard.append([InlineKeyboardButton("➕ Добавить чат", callback_data="add_chat")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def add_chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления чата"""
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "➕ <b>Добавление нового чата</b>\n\n"
        "Чтобы добавить чат или канал:\n"
        "1. Добавьте этого бота в ваш чат/канал\n"
        "2. Сделайте бота администратором (с правами на отправку сообщений)\n"
        "3. Отправьте мне ID чата\n\n"
        "ID чата можно узнать через @RawDataBot\n\n"
        "Введите ID чата (например: -1001234567890):",
        parse_mode="HTML"
    )
    return ADD_CHAT_ID


async def add_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение ID чата"""
    chat_id = update.message.text.strip()

    # Проверяем формат
    if not (chat_id.startswith("-") or chat_id.isdigit()):
        await update.message.reply_text(
            "❌ Неверный формат ID чата.\n"
            "ID должен быть числом (например: -1001234567890)"
        )
        return ADD_CHAT_ID

    context.user_data['new_chat_id'] = chat_id

    await update.message.reply_text(
        "Введите название для этого чата\n"
        "(для вашего удобства):"
    )
    return ADD_CHAT_NAME


async def add_chat_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия чата"""
    chat_name = update.message.text
    chat_id = context.user_data['new_chat_id']

    # Пытаемся отправить тестовое сообщение
    try:
        test_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="✅ Бот успешно подключен к этому чату!"
        )
        await test_msg.delete()

        # Добавляем в БД
        db.add_target_chat(chat_id, chat_name, "unknown")

        await update.message.reply_text(
            f"✅ Чат '{chat_name}' успешно добавлен!\n"
            f"ID: {chat_id}"
        )

    except Exception as e:
        logger.error(f"Error adding chat {chat_id}: {e}")
        await update.message.reply_text(
            f"❌ Не удалось добавить чат.\n"
            f"Убедитесь что:\n"
            f"1. Бот добавлен в чат\n"
            f"2. Бот является администратором\n"
            f"3. ID чата указан верно\n\n"
            f"Ошибка: {str(e)}"
        )

    context.user_data.clear()
    return ConversationHandler.END


async def edit_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Редактирование чата"""
    query = update.callback_query
    await query.answer()

    chat_id = query.data.replace("edit_chat_", "")

    keyboard = [
        [InlineKeyboardButton("🔄 Вкл/Выкл", callback_data=f"toggle_{chat_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"remove_{chat_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="manage_chats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(
        f"Редактирование чата\nID: {chat_id}",
        reply_markup=reply_markup
    )


async def toggle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включение/выключение чата"""
    query = update.callback_query
    await query.answer()

    chat_id = query.data.replace("toggle_", "")
    db.toggle_target_chat(chat_id)

    await query.answer("✅ Статус изменен")
    await manage_chats(update, context)


async def remove_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление чата"""
    query = update.callback_query
    await query.answer()

    chat_id = query.data.replace("remove_", "")
    db.remove_target_chat(chat_id)

    await query.answer("✅ Чат удален")
    await manage_chats(update, context)


# === УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ ===
@owner_only
async def manage_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление администраторами (только для главного администратора)"""
    query = update.callback_query
    await query.answer()

    admins = db.get_admins()

    keyboard = []
    text = "👨‍💼 <b>Управление администраторами</b>\n\n"

    if admins:
        text += "Список администраторов:\n\n"
        for admin in admins:
            username_display = f"@{admin['username']}" if admin['username'] else "Нет username"
            role_emoji = "👑" if admin['role'] == 'owner' else "👤"
            role_text = "Главный администратор" if admin['role'] == 'owner' else "Администратор"

            text += f"{role_emoji} <b>{role_text}</b>\n"
            text += f"   ID: <code>{admin['user_id']}</code>\n"
            text += f"   {username_display}\n"
            text += f"   Добавлен: {admin['added_at'][:10]}\n"

            # Кнопка удаления (только если не owner)
            if admin['role'] != 'owner':
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑 Удалить {username_display}",
                        callback_data=f"remove_admin_{admin['user_id']}"
                    )
                ])
            text += "\n"
    else:
        text += "Нет администраторов.\n"

    keyboard.append([InlineKeyboardButton("➕ Добавить администратора", callback_data="add_admin")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")


@owner_only
async def add_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления администратора (только для главного администратора)"""
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "➕ <b>Добавление нового администратора</b>\n\n"
        "Чтобы добавить администратора:\n"
        "1. Попросите человека написать боту @userinfobot\n"
        "2. Он получит свой Telegram ID\n"
        "3. Отправьте мне этот ID\n\n"
        "⚠️ <i>Новый администратор будет иметь ограниченные права.\n"
        "Он сможет создавать рассылки, но не управлять администраторами.</i>\n\n"
        "Введите Telegram ID нового администратора:",
        parse_mode="HTML"
    )
    return ADD_ADMIN_ID


async def add_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение ID нового администратора"""
    try:
        admin_id = int(update.message.text.strip())

        # Проверяем что такой админ еще не добавлен
        if db.is_admin(admin_id):
            await update.message.reply_text(
                "❌ Этот пользователь уже является администратором!"
            )
            return ConversationHandler.END

        # Добавляем администратора
        if db.add_admin(admin_id):
            await update.message.reply_text(
                f"✅ Администратор успешно добавлен!\n"
                f"ID: <code>{admin_id}</code>\n\n"
                f"Теперь этот пользователь может управлять ботом.",
                parse_mode="HTML"
            )
            logger.info(f"New admin added: {admin_id} by {update.effective_user.id}")
        else:
            await update.message.reply_text(
                "❌ Не удалось добавить администратора. Попробуйте еще раз."
            )

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID.\n"
            "ID должен быть числом (например: 123456789)\n\n"
            "Попробуйте еще раз:"
        )
        return ADD_ADMIN_ID

    return ConversationHandler.END


@owner_only
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление администратора (только для главного администратора)"""
    query = update.callback_query
    await query.answer()

    admin_id = int(query.data.replace("remove_admin_", ""))

    # Защита от удаления owner
    if admin_id == config.FIRST_ADMIN_ID:
        await query.answer("❌ Нельзя удалить главного администратора!", show_alert=True)
        return

    # Удаляем администратора
    if db.remove_admin(admin_id):
        await query.answer("✅ Администратор удален")
        logger.info(f"Admin removed: {admin_id} by {update.effective_user.id}")
    else:
        await query.answer("❌ Ошибка при удалении", show_alert=True)

    # Обновляем меню
    await manage_admins(update, context)


# === СТАТИСТИКА ===
async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать общую статистику"""
    query = update.callback_query
    await query.answer()

    broadcasts = db.get_broadcasts()
    total_sent = 0
    total_delivered = 0
    total_clicks = 0

    for bc in broadcasts:
        stats = db.get_broadcast_stats(bc['id'])
        total_sent += stats['total_sent']
        total_delivered += stats['delivered']
        total_clicks += stats['total_clicks']

    text = (
        "📊 <b>Общая статистика</b>\n\n"
        f"📋 Всего рассылок: {len(broadcasts)}\n"
        f"📤 Отправлено сообщений: {total_sent}\n"
        f"✅ Доставлено: {total_delivered}\n"
        f"🖱 Всего кликов: {total_clicks}\n"
    )

    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")


# === ПОМОЩЬ ===
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать помощь"""
    query = update.callback_query
    if query:
        await query.answer()

    text = (
        "ℹ️ <b>Помощь по использованию бота</b>\n\n"
        "<b>Основные функции:</b>\n\n"
        "📤 <b>Создать рассылку</b>\n"
        "Создание новой рассылки по вашим чатам и каналам.\n\n"
        "📋 <b>Мои рассылки</b>\n"
        "Просмотр всех созданных рассылок и их статистики.\n\n"
        "👥 <b>Управление чатами</b>\n"
        "Добавление, удаление и управление целевыми чатами.\n\n"
        "📊 <b>Статистика</b>\n"
        "Общая статистика по всем рассылкам.\n\n"
        "<b>Как добавить чат:</b>\n"
        "1. Добавьте бота в ваш чат/канал\n"
        "2. Сделайте бота администратором\n"
        "3. Получите ID чата через @RawDataBot\n"
        "4. Добавьте ID через меню 'Управление чатами'\n\n"
        "<b>Команды:</b>\n"
        "/start - Главное меню\n"
        "/help - Показать эту помощь"
    )

    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


# === РЕГИСТРАЦИЯ ПОЛЬЗОВАТЕЛЕЙ ===
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало регистрации пользователя"""
    user_id = update.effective_user.id
    chat_id = str(update.effective_chat.id)

    # Проверяем, зарегистрирован ли уже
    user = db.get_user(user_id, chat_id)

    if user and user.get('gender') and user.get('age'):
        await update.message.reply_text(
            f"✅ Вы уже зарегистрированы!\n\n"
            f"Пол: {'👨 Мужской' if user['gender'] == 'male' else '👩 Женский'}\n"
            f"Возраст: {user['age']} лет\n\n"
            f"Чтобы изменить данные, начните регистрацию заново."
        )
        return ConversationHandler.END

    # Сохраняем базовую информацию
    db.add_or_update_user(
        user_id=user_id,
        chat_id=chat_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name
    )

    keyboard = [
        [InlineKeyboardButton("👨 Мужской", callback_data="reg_gender_male")],
        [InlineKeyboardButton("👩 Женский", callback_data="reg_gender_female")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 Добро пожаловать!\n\n"
        "Для получения персонализированных рассылок, пожалуйста, укажите:\n\n"
        "Ваш пол:",
        reply_markup=reply_markup
    )

    return REGISTER_GENDER


async def register_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора пола"""
    query = update.callback_query
    await query.answer()

    gender = "male" if query.data == "reg_gender_male" else "female"
    context.user_data['register_gender'] = gender

    await query.message.reply_text(
        f"✅ Пол: {'Мужской' if gender == 'male' else 'Женский'}\n\n"
        f"Теперь укажите ваш возраст (например: 25):"
    )

    return REGISTER_AGE


async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода возраста"""
    try:
        age = int(update.message.text)
        if age < 10 or age > 100:
            raise ValueError

        user_id = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        gender = context.user_data.get('register_gender')

        # Сохраняем данные
        db.add_or_update_user(
            user_id=user_id,
            chat_id=chat_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            gender=gender,
            age=age
        )

        await update.message.reply_text(
            "✅ Регистрация завершена!\n\n"
            f"Пол: {'👨 Мужской' if gender == 'male' else '👩 Женский'}\n"
            f"Возраст: {age} лет\n\n"
            "Теперь вы будете получать рассылки, соответствующие вашему профилю!"
        )

        context.user_data.clear()
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректный возраст (от 10 до 100):"
        )
        return REGISTER_AGE


async def view_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр статистики по пользователям (для админов)"""
    query = update.callback_query
    if query:
        await query.answer()

    stats = db.get_user_stats()

    text = (
        "📊 <b>Статистика пользователей</b>\n\n"
        f"👥 Всего зарегистрировано: {stats['total']}\n"
        f"👨 Мужчин: {stats['male']}\n"
        f"👩 Женщин: {stats['female']}\n"
        f"❓ Без данных: {stats['unknown']}\n"
    )

    if stats['avg_age']:
        text += f"📈 Средний возраст: {stats['avg_age']} лет\n"

    # Статистика по чатам
    chats = db.get_target_chats()
    if chats:
        text += "\n<b>По чатам:</b>\n"
        for chat in chats:
            chat_stats = db.get_user_stats(chat['chat_id'])
            text += f"\n📍 {chat['chat_name']}: {chat_stats['total']} чел."

    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def new_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нового участника в чате"""
    for member in update.message.new_chat_members:
        if member.id != context.bot.id:  # Не сам бот
            user_id = member.id
            chat_id = str(update.effective_chat.id)

            # Сохраняем базовую информацию
            db.add_or_update_user(
                user_id=user_id,
                chat_id=chat_id,
                username=member.username,
                first_name=member.first_name
            )

            # Отправляем приветствие с предложением зарегистрироваться
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"👋 Привет, {member.first_name}!\n\n"
                        f"Вы присоединились к чату, который использует нашего бота для рассылок.\n\n"
                        f"Чтобы получать персонализированные рассылки, "
                        f"пройдите быструю регистрацию:\n"
                        f"/register"
                    )
                )
            except Exception as e:
                logger.warning(f"Could not send registration message to user {user_id}: {e}")


# === ОТМЕНА ===
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    await update.message.reply_text("❌ Действие отменено")
    context.user_data.clear()
    return ConversationHandler.END


# === CALLBACK HANDLERS ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query

    if query.data == "main_menu":
        await show_main_menu(update, context)
    elif query.data == "create_broadcast":
        await create_broadcast_start(update, context)
    elif query.data == "list_broadcasts":
        await list_broadcasts(update, context)
    elif query.data == "manage_chats":
        await manage_chats(update, context)
    elif query.data == "manage_admins":
        await manage_admins(update, context)
    elif query.data == "add_admin":
        return await add_admin_start(update, context)
    elif query.data.startswith("remove_admin_"):
        await remove_admin(update, context)
    elif query.data == "statistics":
        await show_statistics(update, context)
    elif query.data == "user_stats":
        await view_user_stats(update, context)
    elif query.data == "help":
        await show_help(update, context)
    elif query.data.startswith("view_broadcast_"):
        await view_broadcast(update, context)
    elif query.data.startswith("delete_broadcast_"):
        await delete_broadcast(update, context)
    elif query.data.startswith("edit_chat_"):
        await edit_chat(update, context)
    elif query.data.startswith("toggle_") and not query.data.startswith("toggle_chat_"):
        await toggle_chat(update, context)
    elif query.data.startswith("remove_"):
        await remove_chat(update, context)
    elif query.data == "add_chat":
        await add_chat_start(update, context)


def main():
    """Запуск бота"""
    global scheduler

    # Проверка конфигурации
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен! Проверьте файл .env")
        return

    if not config.FIRST_ADMIN_ID:
        logger.error("FIRST_ADMIN_ID не установлен! Проверьте файл .env")
        return

    # Создаем приложение
    application = Application.builder().token(config.BOT_TOKEN).build()

    # Создаем планировщик
    scheduler = BroadcastScheduler(application.bot, db)
    scheduler.start()

    # === ОБРАБОТЧИКИ ===

    # Создание рассылки (ConversationHandler)
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_broadcast_start, pattern="^create_broadcast$")],
        states={
            BROADCAST_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_title)],
            BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text)],
            BROADCAST_CHATS: [
                CallbackQueryHandler(toggle_chat_selection, pattern="^toggle_chat_"),
                CallbackQueryHandler(chats_selected, pattern="^chats_selected$")
            ],
            BROADCAST_TIME: [
                CallbackQueryHandler(broadcast_time, pattern="^time_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_time_custom)
            ],
            BROADCAST_FREQUENCY: [CallbackQueryHandler(broadcast_frequency, pattern="^freq_")],
            BROADCAST_REPEAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_repeat)],
            BROADCAST_GENDER: [CallbackQueryHandler(broadcast_gender, pattern="^gender_")],
            BROADCAST_AGE_MIN: [
                CallbackQueryHandler(broadcast_age, pattern="^age_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_age_min)
            ],
            BROADCAST_AGE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_age_max)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавление чата (ConversationHandler)
    add_chat_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_chat_start, pattern="^add_chat$")],
        states={
            ADD_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_chat_id)],
            ADD_CHAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_chat_name)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Регистрация пользователя (ConversationHandler)
    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REGISTER_GENDER: [CallbackQueryHandler(register_gender, pattern="^reg_gender_")],
            REGISTER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_age)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавление администратора (ConversationHandler)
    add_admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_admin_start, pattern="^add_admin$")],
        states={
            ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_id)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CommandHandler("register", register_start))

    # ConversationHandlers
    application.add_handler(broadcast_conv)
    application.add_handler(add_chat_conv)
    application.add_handler(register_conv)
    application.add_handler(add_admin_conv)

    # Обработчик новых участников чата
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_chat_member))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(button_handler))

    # Настройка меню команд
    async def setup_commands(app):
        """Настройка кнопки меню с командами"""
        commands = [
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("register", "👤 Зарегистрироваться"),
            BotCommand("help", "ℹ️ Помощь"),
            BotCommand("cancel", "❌ Отменить текущее действие")
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Menu commands set up")

    application.post_init = setup_commands

    # Запуск бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
