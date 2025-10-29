import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional


class Database:
    def __init__(self, db_path="broadcast_bot.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Таблица администраторов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'admin',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция: добавляем поле role если его нет
        cursor.execute("PRAGMA table_info(admins)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'role' not in columns:
            cursor.execute("ALTER TABLE admins ADD COLUMN role TEXT DEFAULT 'admin'")
            conn.commit()

        # Обновляем роль первого админа на 'owner' (из config)
        from config import FIRST_ADMIN_ID
        if FIRST_ADMIN_ID:
            cursor.execute("UPDATE admins SET role = 'owner' WHERE user_id = ?", (FIRST_ADMIN_ID,))
            conn.commit()

        # Таблица целевых чатов/каналов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS target_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                chat_name TEXT,
                chat_type TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Таблица рассылок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                message_text TEXT,
                target_chats TEXT,
                scheduled_time TIMESTAMP,
                frequency TEXT,
                repeat_count INTEGER DEFAULT 1,
                current_repeat INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tracking_enabled INTEGER DEFAULT 1
            )
        """)

        # Таблица статистики
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id INTEGER,
                chat_id TEXT,
                sent_at TIMESTAMP,
                delivered INTEGER DEFAULT 1,
                views INTEGER DEFAULT 0,
                clicks INTEGER DEFAULT 0,
                FOREIGN KEY (broadcast_id) REFERENCES broadcasts(id)
            )
        """)

        # Таблица для трекинга ссылок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS link_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id INTEGER,
                original_url TEXT,
                short_code TEXT UNIQUE,
                clicks INTEGER DEFAULT 0,
                FOREIGN KEY (broadcast_id) REFERENCES broadcasts(id)
            )
        """)

        # Таблица пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id TEXT,
                username TEXT,
                first_name TEXT,
                gender TEXT,
                age INTEGER,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, chat_id)
            )
        """)

        # Обновляем таблицу broadcasts - добавляем поля для фильтров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                message_text TEXT,
                target_chats TEXT,
                scheduled_time TIMESTAMP,
                frequency TEXT,
                repeat_count INTEGER DEFAULT 1,
                current_repeat INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tracking_enabled INTEGER DEFAULT 1,
                gender_filter TEXT,
                age_min INTEGER,
                age_max INTEGER
            )
        """)

        # Проверяем, нужна ли миграция
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='broadcasts'")
        if cursor.fetchone():
            # Проверяем наличие новых полей
            cursor.execute("PRAGMA table_info(broadcasts)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'gender_filter' not in columns:
                # Миграция: копируем данные
                cursor.execute("""
                    INSERT INTO broadcasts_new
                    (id, title, message_text, target_chats, scheduled_time, frequency,
                     repeat_count, current_repeat, status, created_at, tracking_enabled)
                    SELECT id, title, message_text, target_chats, scheduled_time, frequency,
                           repeat_count, current_repeat, status, created_at, tracking_enabled
                    FROM broadcasts
                """)
                cursor.execute("DROP TABLE broadcasts")
                cursor.execute("ALTER TABLE broadcasts_new RENAME TO broadcasts")

        conn.commit()
        conn.close()

    # === АДМИНИСТРАТОРЫ ===
    def add_admin(self, user_id: int, username: str = None, role: str = 'admin'):
        """Добавить администратора. role: 'owner' (главный) или 'admin' (обычный)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO admins (user_id, username, role) VALUES (?, ?, ?)",
                          (user_id, username, role))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding admin: {e}")
            return False
        finally:
            conn.close()

    def is_admin(self, user_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def get_admins(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, role, added_at FROM admins")
        admins = [{"user_id": row[0], "username": row[1], "role": row[2], "added_at": row[3]}
                 for row in cursor.fetchall()]
        conn.close()
        return admins

    def is_owner(self, user_id: int) -> bool:
        """Проверить является ли пользователь главным администратором"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM admins WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None and result[0] == 'owner'

    def remove_admin(self, user_id: int):
        """Удалить администратора"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error removing admin: {e}")
            return False
        finally:
            conn.close()

    # === ЦЕЛЕВЫЕ ЧАТЫ ===
    def add_target_chat(self, chat_id: str, chat_name: str, chat_type: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO target_chats (chat_id, chat_name, chat_type)
                VALUES (?, ?, ?)
            """, (chat_id, chat_name, chat_type))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding target chat: {e}")
            return False
        finally:
            conn.close()

    def get_target_chats(self, active_only=True) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        query = "SELECT id, chat_id, chat_name, chat_type, is_active FROM target_chats"
        if active_only:
            query += " WHERE is_active = 1"
        cursor.execute(query)
        chats = [{"id": row[0], "chat_id": row[1], "chat_name": row[2],
                 "chat_type": row[3], "is_active": row[4]}
                for row in cursor.fetchall()]
        conn.close()
        return chats

    def toggle_target_chat(self, chat_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE target_chats
            SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
            WHERE chat_id = ?
        """, (chat_id,))
        conn.commit()
        conn.close()

    def remove_target_chat(self, chat_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM target_chats WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()

    # === РАССЫЛКИ ===
    def create_broadcast(self, title: str, message_text: str, target_chats: List[str],
                        scheduled_time: datetime, frequency: str = "once",
                        repeat_count: int = 1, gender_filter: str = None,
                        age_min: int = None, age_max: int = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO broadcasts (title, message_text, target_chats, scheduled_time,
                                  frequency, repeat_count, gender_filter, age_min, age_max)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, message_text, json.dumps(target_chats),
              scheduled_time.isoformat(), frequency, repeat_count,
              gender_filter, age_min, age_max))
        broadcast_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return broadcast_id

    def get_broadcast(self, broadcast_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, message_text, target_chats, scheduled_time,
                   frequency, repeat_count, current_repeat, status, created_at,
                   gender_filter, age_min, age_max
            FROM broadcasts WHERE id = ?
        """, (broadcast_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "id": row[0], "title": row[1], "message_text": row[2],
                "target_chats": json.loads(row[3]), "scheduled_time": row[4],
                "frequency": row[5], "repeat_count": row[6],
                "current_repeat": row[7], "status": row[8], "created_at": row[9],
                "gender_filter": row[10], "age_min": row[11], "age_max": row[12]
            }
        return None

    def get_broadcasts(self, status: str = None) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        query = """
            SELECT id, title, scheduled_time, frequency, repeat_count,
                   current_repeat, status
            FROM broadcasts
        """
        if status:
            query += f" WHERE status = '{status}'"
        query += " ORDER BY created_at DESC"

        cursor.execute(query)
        broadcasts = [{"id": row[0], "title": row[1], "scheduled_time": row[2],
                      "frequency": row[3], "repeat_count": row[4],
                      "current_repeat": row[5], "status": row[6]}
                     for row in cursor.fetchall()]
        conn.close()
        return broadcasts

    def update_broadcast_status(self, broadcast_id: int, status: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE broadcasts SET status = ? WHERE id = ?",
                      (status, broadcast_id))
        conn.commit()
        conn.close()

    def increment_broadcast_repeat(self, broadcast_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE broadcasts
            SET current_repeat = current_repeat + 1
            WHERE id = ?
        """, (broadcast_id,))
        conn.commit()
        conn.close()

    def delete_broadcast(self, broadcast_id: int):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM broadcasts WHERE id = ?", (broadcast_id,))
        cursor.execute("DELETE FROM statistics WHERE broadcast_id = ?", (broadcast_id,))
        conn.commit()
        conn.close()

    # === СТАТИСТИКА ===
    def add_broadcast_stat(self, broadcast_id: int, chat_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO statistics (broadcast_id, chat_id, sent_at)
            VALUES (?, ?, ?)
        """, (broadcast_id, chat_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def get_broadcast_stats(self, broadcast_id: int) -> Dict:
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) as total_sent,
                   SUM(delivered) as delivered,
                   SUM(views) as total_views,
                   SUM(clicks) as total_clicks
            FROM statistics WHERE broadcast_id = ?
        """, (broadcast_id,))

        row = cursor.fetchone()
        conn.close()

        return {
            "total_sent": row[0] or 0,
            "delivered": row[1] or 0,
            "total_views": row[2] or 0,
            "total_clicks": row[3] or 0
        }

    def record_click(self, broadcast_id: int, chat_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE statistics
            SET clicks = clicks + 1
            WHERE broadcast_id = ? AND chat_id = ?
        """, (broadcast_id, chat_id))
        conn.commit()
        conn.close()

    # === ПОЛЬЗОВАТЕЛИ ===
    def add_or_update_user(self, user_id: int, chat_id: str, username: str = None,
                          first_name: str = None, gender: str = None, age: int = None):
        """Добавить или обновить пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO users (user_id, chat_id, username, first_name, gender, age)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, chat_id) DO UPDATE SET
                    username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    gender = COALESCE(?, gender),
                    age = COALESCE(?, age)
            """, (user_id, chat_id, username, first_name, gender, age,
                  username, first_name, gender, age))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding/updating user: {e}")
            return False
        finally:
            conn.close()

    def get_user(self, user_id: int, chat_id: str) -> Optional[Dict]:
        """Получить информацию о пользователе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, chat_id, username, first_name, gender, age, registered_at
            FROM users WHERE user_id = ? AND chat_id = ?
        """, (user_id, chat_id))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "user_id": row[0], "chat_id": row[1], "username": row[2],
                "first_name": row[3], "gender": row[4], "age": row[5],
                "registered_at": row[6]
            }
        return None

    def get_users_in_chat(self, chat_id: str, gender: str = None,
                         age_min: int = None, age_max: int = None) -> List[Dict]:
        """Получить пользователей чата с фильтрацией"""
        conn = self.get_connection()
        cursor = conn.cursor()

        query = "SELECT user_id, username, first_name, gender, age FROM users WHERE chat_id = ?"
        params = [chat_id]

        if gender and gender != "all":
            query += " AND gender = ?"
            params.append(gender)

        if age_min is not None:
            query += " AND age >= ?"
            params.append(age_min)

        if age_max is not None:
            query += " AND age <= ?"
            params.append(age_max)

        cursor.execute(query, params)
        users = [{"user_id": row[0], "username": row[1], "first_name": row[2],
                 "gender": row[3], "age": row[4]}
                for row in cursor.fetchall()]
        conn.close()
        return users

    def get_user_count(self, chat_id: str = None) -> int:
        """Получить количество зарегистрированных пользователей"""
        conn = self.get_connection()
        cursor = conn.cursor()

        if chat_id:
            cursor.execute("SELECT COUNT(*) FROM users WHERE chat_id = ?", (chat_id,))
        else:
            cursor.execute("SELECT COUNT(*) FROM users")

        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_user_stats(self, chat_id: str = None) -> Dict:
        """Получить статистику по пользователям"""
        conn = self.get_connection()
        cursor = conn.cursor()

        base_query = "FROM users" + (" WHERE chat_id = ?" if chat_id else "")
        params = [chat_id] if chat_id else []

        cursor.execute(f"SELECT COUNT(*) {base_query}", params)
        total = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) {base_query} AND gender = 'male'", params)
        male = cursor.fetchone()[0]

        cursor.execute(f"SELECT COUNT(*) {base_query} AND gender = 'female'", params)
        female = cursor.fetchone()[0]

        cursor.execute(f"SELECT AVG(age) {base_query} AND age IS NOT NULL", params)
        avg_age = cursor.fetchone()[0]

        conn.close()

        return {
            "total": total,
            "male": male,
            "female": female,
            "unknown": total - male - female,
            "avg_age": round(avg_age, 1) if avg_age else None
        }
