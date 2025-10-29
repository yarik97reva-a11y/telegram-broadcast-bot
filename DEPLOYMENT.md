# 🚀 Деплой бота на сервер

## Варианты размещения:

1. **Railway.app** - ⭐ РЕКОМЕНДУЕТСЯ (бесплатно, просто)
2. **Render.com** - бесплатно, просто
3. **VPS** - полный контроль, $5/месяц

---

## ⭐ ВАРИАНТ 1: Railway.app (САМЫЙ ПРОСТОЙ)

### Почему Railway?
- ✅ **БЕСПЛАТНО** (500 часов в месяц - этого хватит)
- ✅ Очень простой интерфейс
- ✅ Автоматический деплой из GitHub
- ✅ Не нужно знать Docker/Linux

### Шаги установки:

#### 1️⃣ Подготовка (один раз)

**A. Создайте GitHub репозиторий**

```bash
cd ~/telegram_broadcast_bot

# Инициализируем git (если еще не сделали)
git init

# Добавляем все файлы
git add .

# Создаем первый коммит
git commit -m "Initial commit - Telegram broadcast bot"

# Создайте репозиторий на GitHub.com
# Затем добавьте remote и запушьте:
git remote add origin https://github.com/ваш_username/telegram_broadcast_bot.git
git branch -M main
git push -u origin main
```

#### 2️⃣ Деплой на Railway

**A. Регистрация**
1. Зайдите на https://railway.app
2. Нажмите "Start a New Project"
3. Войдите через GitHub

**B. Создание проекта**
1. Нажмите "Deploy from GitHub repo"
2. Выберите ваш репозиторий `telegram_broadcast_bot`
3. Railway автоматически определит Python проект

**C. Настройка переменных окружения**
1. Откройте ваш проект в Railway
2. Перейдите в "Variables"
3. Добавьте переменные:
   ```
   BOT_TOKEN=ваш_токен_от_botfather
   FIRST_ADMIN_ID=ваш_telegram_id
   DATABASE_PATH=broadcast_bot.db
   TIMEZONE=Europe/Moscow
   ```

**D. Запуск**
1. Railway автоматически запустит бота
2. Проверьте логи во вкладке "Deployments"
3. Должно быть: "Бот запущен!"

#### ✅ ГОТОВО!

Бот теперь работает 24/7!

---

## 🔵 ВАРИАНТ 2: Render.com (АЛЬТЕРНАТИВА)

### Шаги:

1. Зайдите на https://render.com
2. Создайте аккаунт
3. New → Background Worker
4. Подключите GitHub репозиторий
5. Настройки:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
6. Добавьте Environment Variables (как в Railway)
7. Нажмите "Create Web Service"

Бот запустится автоматически!

---

## 💻 ВАРИАНТ 3: VPS (для продвинутых)

### Рекомендуемые провайдеры:
- **Hetzner** - €4/месяц (Европа)
- **Digital Ocean** - $6/месяц
- **Contabo** - €4/месяц

### Пошаговая инструкция:

#### 1️⃣ Купите и настройте VPS

1. Купите VPS с Ubuntu 22.04
2. Подключитесь по SSH:
   ```bash
   ssh root@your_server_ip
   ```

#### 2️⃣ Установите зависимости

```bash
# Обновите систему
apt update && apt upgrade -y

# Установите Python и необходимые пакеты
apt install -y python3 python3-pip python3-venv git

# Создайте пользователя для бота
adduser botuser
usermod -aG sudo botuser
su - botuser
```

#### 3️⃣ Загрузите бота на сервер

**Вариант A: Через Git (рекомендуется)**
```bash
cd ~
git clone https://github.com/ваш_username/telegram_broadcast_bot.git
cd telegram_broadcast_bot
```

**Вариант B: Через SCP (с вашего компьютера)**
```bash
# На вашем Mac:
scp -r ~/telegram_broadcast_bot botuser@your_server_ip:~/
```

#### 4️⃣ Установите бота

```bash
cd ~/telegram_broadcast_bot

# Создайте виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установите зависимости
pip install -r requirements.txt

# Создайте .env файл
nano .env
```

Вставьте:
```env
BOT_TOKEN=ваш_токен
FIRST_ADMIN_ID=ваш_id
DATABASE_PATH=broadcast_bot.db
TIMEZONE=Europe/Moscow
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

#### 5️⃣ Настройте автозапуск (systemd)

```bash
# Создайте service файл
sudo nano /etc/systemd/system/telegram-bot.service
```

Вставьте:
```ini
[Unit]
Description=Telegram Broadcast Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/telegram_broadcast_bot
Environment="PATH=/home/botuser/telegram_broadcast_bot/venv/bin"
ExecStart=/home/botuser/telegram_broadcast_bot/venv/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Сохраните: `Ctrl+O`, `Enter`, `Ctrl+X`

#### 6️⃣ Запустите бота

```bash
# Перезагрузите systemd
sudo systemctl daemon-reload

# Включите автозапуск
sudo systemctl enable telegram-bot

# Запустите бота
sudo systemctl start telegram-bot

# Проверьте статус
sudo systemctl status telegram-bot
```

#### 7️⃣ Полезные команды

```bash
# Просмотр логов
sudo journalctl -u telegram-bot -f

# Перезапуск бота
sudo systemctl restart telegram-bot

# Остановка бота
sudo systemctl stop telegram-bot

# Проверка статуса
sudo systemctl status telegram-bot
```

#### ✅ ГОТОВО!

Бот работает 24/7 на вашем VPS!

---

## 🔄 Обновление бота

### На Railway/Render:
1. Внесите изменения в код локально
2. Закоммитьте и запушьте в GitHub:
   ```bash
   git add .
   git commit -m "Update bot"
   git push
   ```
3. Railway/Render автоматически обновят бота

### На VPS:
```bash
ssh botuser@your_server_ip
cd ~/telegram_broadcast_bot
git pull
sudo systemctl restart telegram-bot
```

---

## 📊 Мониторинг

### Railway:
- Логи: Dashboard → Deployments → View Logs
- Метрики: Dashboard → Metrics

### VPS:
```bash
# Логи в реальном времени
sudo journalctl -u telegram-bot -f

# Последние 100 строк
sudo journalctl -u telegram-bot -n 100

# Проверка работы
sudo systemctl status telegram-bot
```

---

## ❓ Часто задаваемые вопросы

**Q: Сколько стоит Railway?**
A: Бесплатно до 500 часов в месяц (этого хватит для одного бота 24/7)

**Q: Что лучше - Railway или VPS?**
A: Railway - если хотите просто и быстро. VPS - если нужен полный контроль и планируете много ботов.

**Q: Бот перестал работать на Railway**
A: Проверьте логи в Railway Dashboard. Возможно закончились бесплатные часы (добавьте $5).

**Q: Как посмотреть логи на VPS?**
A: `sudo journalctl -u telegram-bot -f`

**Q: База данных сохраняется при перезапуске?**
A: Да, SQLite файл сохраняется. На Railway используется Volume для хранения.

---

## 🎉 Поздравляем!

Ваш бот теперь работает 24/7 в облаке! 🚀
