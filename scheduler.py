from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from database import Database
import pytz
import logging

logger = logging.getLogger(__name__)

# Московское время (UTC+3)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')


class BroadcastScheduler:
    def __init__(self, bot, db: Database):
        self.scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
        self.bot = bot
        self.db = db

    def start(self):
        """Запуск планировщика"""
        self.scheduler.start()
        logger.info("Scheduler started")

    def schedule_broadcast(self, broadcast_id: int):
        """Планирование рассылки"""
        broadcast = self.db.get_broadcast(broadcast_id)
        if not broadcast:
            logger.error(f"Broadcast {broadcast_id} not found")
            return

        scheduled_time = datetime.fromisoformat(broadcast["scheduled_time"])
        frequency = broadcast["frequency"]

        if frequency == "once":
            # Одноразовая рассылка
            self.scheduler.add_job(
                self.send_broadcast,
                trigger=DateTrigger(run_date=scheduled_time),
                args=[broadcast_id],
                id=f"broadcast_{broadcast_id}",
                replace_existing=True
            )
            logger.info(f"Scheduled one-time broadcast {broadcast_id} at {scheduled_time}")

        elif frequency in ["hourly", "daily", "weekly"]:
            # Периодическая рассылка
            interval_map = {
                "hourly": {"hours": 1},
                "daily": {"days": 1},
                "weekly": {"weeks": 1}
            }
            self.scheduler.add_job(
                self.send_broadcast,
                trigger=IntervalTrigger(
                    start_date=scheduled_time,
                    **interval_map[frequency]
                ),
                args=[broadcast_id],
                id=f"broadcast_{broadcast_id}",
                replace_existing=True
            )
            logger.info(f"Scheduled {frequency} broadcast {broadcast_id} starting at {scheduled_time}")

    async def send_broadcast(self, broadcast_id: int):
        """Отправка рассылки"""
        try:
            broadcast = self.db.get_broadcast(broadcast_id)
            if not broadcast:
                logger.error(f"Broadcast {broadcast_id} not found")
                return

            # Проверка на количество повторов
            if broadcast["current_repeat"] >= broadcast["repeat_count"]:
                self.db.update_broadcast_status(broadcast_id, "completed")
                self.cancel_broadcast(broadcast_id)
                logger.info(f"Broadcast {broadcast_id} completed all repeats")
                return

            # Параметры рассылки
            message_text = broadcast["message_text"]
            target_chats = broadcast["target_chats"]
            gender_filter = broadcast.get("gender_filter")
            age_min = broadcast.get("age_min")
            age_max = broadcast.get("age_max")

            success_count = 0
            fail_count = 0

            # Проверяем, нужна ли фильтрация
            has_filters = gender_filter or age_min is not None or age_max is not None

            for chat_id in target_chats:
                if has_filters:
                    # С фильтрами - отправляем личные сообщения пользователям
                    users = self.db.get_users_in_chat(
                        chat_id,
                        gender=gender_filter,
                        age_min=age_min,
                        age_max=age_max
                    )

                    if not users:
                        logger.warning(f"No users matching filters in chat {chat_id}")
                        continue

                    for user in users:
                        try:
                            await self.bot.send_message(
                                chat_id=user["user_id"],
                                text=message_text,
                                parse_mode="HTML"
                            )
                            success_count += 1
                            logger.info(f"Sent broadcast {broadcast_id} to user {user['user_id']} in chat {chat_id}")
                        except Exception as e:
                            fail_count += 1
                            logger.error(f"Failed to send to user {user['user_id']}: {e}")

                    self.db.add_broadcast_stat(broadcast_id, chat_id)
                else:
                    # Без фильтров - отправляем всем участникам чата в личные сообщения
                    users = self.db.get_users_in_chat(chat_id)

                    if not users:
                        logger.warning(f"No registered users in chat {chat_id}")
                        continue

                    for user in users:
                        try:
                            await self.bot.send_message(
                                chat_id=user["user_id"],
                                text=message_text,
                                parse_mode="HTML"
                            )
                            success_count += 1
                            logger.info(f"Sent broadcast {broadcast_id} to user {user['user_id']} in chat {chat_id}")
                        except Exception as e:
                            fail_count += 1
                            logger.error(f"Failed to send to user {user['user_id']}: {e}")

                    self.db.add_broadcast_stat(broadcast_id, chat_id)

            # Обновление статуса
            self.db.increment_broadcast_repeat(broadcast_id)

            # Если одноразовая рассылка - завершаем
            if broadcast["frequency"] == "once":
                self.db.update_broadcast_status(broadcast_id, "completed")
                self.cancel_broadcast(broadcast_id)
            else:
                self.db.update_broadcast_status(broadcast_id, "active")

            logger.info(f"Broadcast {broadcast_id} sent: {success_count} success, {fail_count} failed")

        except Exception as e:
            logger.error(f"Error sending broadcast {broadcast_id}: {e}")
            self.db.update_broadcast_status(broadcast_id, "failed")

    def cancel_broadcast(self, broadcast_id: int):
        """Отмена запланированной рассылки"""
        job_id = f"broadcast_{broadcast_id}"
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Cancelled broadcast {broadcast_id}")
        except Exception as e:
            logger.warning(f"Could not cancel broadcast {broadcast_id}: {e}")

    def get_scheduled_jobs(self):
        """Получение списка запланированных задач"""
        return self.scheduler.get_jobs()

    def shutdown(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")
