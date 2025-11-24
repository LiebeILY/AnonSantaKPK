import requests
import time
import sqlite3
import logging
import random
from config import BOT_TOKEN, ORGANIZER_IDS

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class SimpleSantaBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.last_update_id = 0
        self.user_data = {}
        
    def init_database(self):
        """Initialize database"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                fio TEXT,
                group_name TEXT,
                preferences TEXT,
                santa_id INTEGER,
                gift_delivered BOOLEAN DEFAULT 0,
                gift_received BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS event_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                registration_open BOOLEAN DEFAULT 1,
                event_started BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            INSERT OR IGNORE INTO event_settings (id, registration_open, event_started)
            VALUES (1, 1, 0)
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized")
    
    def is_registration_open(self):
        """Check if registration is open"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("SELECT registration_open FROM event_settings WHERE id = 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else False
    
    def is_event_started(self):
        """Check if event has started"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("SELECT event_started FROM event_settings WHERE id = 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else False
    
    def make_request(self, method, params=None, json_data=None):
        """Make request with retry logic"""
        url = self.base_url + method
        
        for attempt in range(3):
            try:
                if json_data:
                    response = requests.post(url, json=json_data, timeout=20)
                else:
                    response = requests.get(url, params=params, timeout=20)
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(f"HTTP {response.status_code} on attempt {attempt + 1}")
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout on attempt {attempt + 1}")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error on attempt {attempt + 1}")
            except Exception as e:
                logger.error(f"Error on attempt {attempt + 1}: {e}")
            
            if attempt < 2:  # Don't sleep after last attempt
                time.sleep(2)
        
        return None
    
    def get_updates(self):
        """Get new messages"""
        params = {
            "offset": self.last_update_id + 1,
            "timeout": 10,
            "limit": 100
        }
        
        result = self.make_request("getUpdates", params=params)
        if result and result.get("ok"):
            return result.get("result", [])
        return []
    
    def send_message(self, chat_id, text):
        """Send message to user"""
        json_data = {
            "chat_id": chat_id,
            "text": text
        }
        
        result = self.make_request("sendMessage", json_data=json_data)
        if result and result.get("ok"):
            logger.info(f"Message sent to {chat_id}")
            return True
        else:
            logger.error(f"Failed to send message to {chat_id}")
            return False
    
    def handle_start(self, chat_id, user_id, user_name):
        """Handle /start command"""
        # Check if user exists in database
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
        existing_user = cursor.fetchone()
        conn.close()
        
        if existing_user:
            if self.is_event_started():
                # If event started, show assignment
                self.show_assignment(chat_id, existing_user[0])
            else:
                self.send_message(chat_id, f"Привет, {existing_user[2]}! Ты уже зарегистрирован.\nТвой ID: Тайный Дед Мороз {existing_user[0]}\n\nЖди начала мероприятия!")
            return
        
        if not self.is_registration_open():
            self.send_message(chat_id, "Регистрация на мероприятие закрыта! 🎅")
            return
        
        # Start registration
        self.send_message(chat_id, f"Привет, {user_name}! 🎄\nДобро пожаловать в Тайного Деда Мороза!\n\nВведи свое ФИО:")
        self.user_data[user_id] = {"step": "fio"}
    
    def show_assignment(self, chat_id, user_db_id):
        """Show user who they should gift to"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        
        # Get who this user should gift to
        cursor.execute("SELECT santa_id FROM users WHERE id = ?", (user_db_id,))
        result = cursor.fetchone()
        
        if result and result[0]:
            receiver_id = result[0]
            # Get receiver's preferences
            cursor.execute("SELECT preferences FROM users WHERE id = ?", (receiver_id,))
            preferences_result = cursor.fetchone()
            preferences = preferences_result[0] if preferences_result else "Не указано"
            
            message = f"""🎅 Ты даришь подарок Тайному Деду Морозу {receiver_id}

Его предпочтения:
{preferences}

📦 Принести подарок необходимо в аудиторию 257 до 18 декабря.
✏️ Не забудь подписать на подарке ID {receiver_id}"""
            
            self.send_message(chat_id, message)
        else:
            self.send_message(chat_id, "Жеребьевка еще не проведена или произошла ошибка.")
        
        conn.close()
    
    def handle_admin_commands(self, chat_id, text, user_id):
        """Handle admin commands"""
        if user_id not in ORGANIZER_IDS:
            self.send_message(chat_id, "У вас нет прав администратора")
            return
        
        if text == "/stats":
            conn = sqlite3.connect('santa.db')
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE gift_delivered = 1")
            delivered_gifts = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE gift_received = 1")
            received_gifts = cursor.fetchone()[0]
            
            conn.close()
            
            message = f"""📊 Статистика мероприятия:

👥 Зарегистрировано участников: {total_users}
🎁 Подарков доставлено: {delivered_gifts}
🎁 Подарков получено: {received_gifts}

Регистрация: {"✅ Открыта" if self.is_registration_open() else "❌ Закрыта"}
Мероприятие: {"✅ Началось" if self.is_event_started() else "❌ Не началось"}"""
            
            self.send_message(chat_id, message)
        
        elif text == "/users":
            users = self.get_all_users()
            if not users:
                self.send_message(chat_id, "Нет зарегистрированных пользователей")
                return
            
            message = "📋 Список участников:\n\n"
            for user in users:
                delivered = "✅" if user[6] else "❌"
                received = "✅" if user[7] else "❌"
                message += f"🎅 {user[2]} (ID: {user[0]})\nГруппа: {user[3]}\nПодарок: {delivered} Получен: {received}\n\n"
            
            self.send_message(chat_id, message)
        
        elif text == "/close":
            self.close_registration()
            self.send_message(chat_id, "✅ Регистрация закрыта!")
        
        elif text == "/open":
            self.open_registration()
            self.send_message(chat_id, "✅ Регистрация открыта!")
        
        elif text == "/start_event":
            count = self.start_santa()
            if count > 1:
                self.send_message(chat_id, f"✅ Жеребьевка завершена! Участников: {count}")
                # Notify all users
                self.notify_all_users()
            else:
                self.send_message(chat_id, "❌ Для жеребьевки нужно минимум 2 участника")
        
        elif text.startswith("/del "):
            try:
                user_id_to_delete = int(text.split()[1])
                user_info = self.delete_user(user_id_to_delete)
                if user_info:
                    self.send_message(chat_id, f"✅ Пользователь удален:\nID: {user_info[0]}\nФИО: {user_info[2]}\nГруппа: {user_info[3]}")
                    # Если мероприятие уже началось, нужно перепровести жеребьевку
                    if self.is_event_started():
                        self.send_message(chat_id, "⚠️ Мероприятие уже началось. Рекомендуется перепровести жеребьевку командой /start_event")
                else:
                    self.send_message(chat_id, "❌ Пользователь с таким ID не найден")
            except (IndexError, ValueError):
                self.send_message(chat_id, "Использование: /del <ID>\n\nНапример: /del 5")
        
        elif text.startswith("/gift "):
            try:
                user_id_to_mark = int(text.split()[1])
                if self.mark_gift_delivered(user_id_to_mark):
                    self.send_message(chat_id, f"✅ Подарок от Тайного Деда Мороза {user_id_to_mark} отмечен как доставленный")
                    # Notify the receiver
                    self.notify_gift_delivered(user_id_to_mark)
                else:
                    self.send_message(chat_id, "❌ Пользователь не найден")
            except (IndexError, ValueError):
                self.send_message(chat_id, "Использование: /gift <ID>\n\nНапример: /gift 3")
        
        elif text.startswith("/received "):
            try:
                user_id_to_mark = int(text.split()[1])
                if self.mark_gift_received(user_id_to_mark):
                    self.send_message(chat_id, f"✅ Подарок для Тайного Деда Мороза {user_id_to_mark} отмечен как полученный")
                else:
                    self.send_message(chat_id, "❌ Пользователь не найден")
            except (IndexError, ValueError):
                self.send_message(chat_id, "Использование: /received <ID>\n\nНапример: /received 7")
        
        elif text == "/help_admin":
            message = """🎅 Команды организатора:

/stats - статистика
/users - список участников  
/close - закрыть регистрацию
/open - открыть регистрацию
/start_event - начать жеребьевку
/del <ID> - удалить участника
/gift <ID> - отметить доставку подарка
/received <ID> - отметить получение подарка

📝 Примеры:
/del 5
/gift 3
/received 7"""
            self.send_message(chat_id, message)
    
    def get_all_users(self):
        """Get all registered users"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        conn.close()
        return users
    
    def close_registration(self):
        """Close registration"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE event_settings SET registration_open = 0 WHERE id = 1")
        conn.commit()
        conn.close()
    
    def open_registration(self):
        """Open registration"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE event_settings SET registration_open = 1 WHERE id = 1")
        conn.commit()
        conn.close()
    
    def start_santa(self):
        """Start secret santa assignment"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        
        # Get all users
        cursor.execute("SELECT id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        
        if len(users) < 2:
            conn.close()
            return len(users)
        
        # Shuffle and create pairs
        random.shuffle(users)
        
        for i in range(len(users)):
            giver = users[i]
            receiver = users[(i + 1) % len(users)]
            cursor.execute("UPDATE users SET santa_id = ? WHERE id = ?", (receiver, giver))
        
        cursor.execute("UPDATE event_settings SET event_started = 1 WHERE id = 1")
        conn.commit()
        conn.close()
        
        return len(users)
    
    def delete_user(self, user_db_id):
        """Delete user from database"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        
        # Get user info before deletion
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_db_id,))
        user_info = cursor.fetchone()
        
        if user_info:
            # Delete the user
            cursor.execute("DELETE FROM users WHERE id = ?", (user_db_id,))
            conn.commit()
        
        conn.close()
        return user_info
    
    def notify_all_users(self):
        """Notify all users about their assignments"""
        users = self.get_all_users()
        for user in users:
            self.show_assignment(user[1], user[0])  # user[1] is telegram_id, user[0] is db_id
    
    def mark_gift_delivered(self, user_db_id):
        """Mark gift as delivered"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET gift_delivered = 1 WHERE id = ?", (user_db_id,))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    
    def mark_gift_received(self, user_db_id):
        """Mark gift as received"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET gift_received = 1 WHERE id = ?", (user_db_id,))
        conn.commit()
        success = cursor.rowcount > 0
        conn.close()
        return success
    
    def notify_gift_delivered(self, user_db_id):
        """Notify receiver that their gift was delivered"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        
        # Find who is giving to this user
        cursor.execute("SELECT id FROM users WHERE santa_id = ?", (user_db_id,))
        giver_result = cursor.fetchone()
        
        if giver_result:
            giver_id = giver_result[0]
            # Get receiver's telegram_id
            cursor.execute("SELECT telegram_id FROM users WHERE id = ?", (user_db_id,))
            receiver_telegram = cursor.fetchone()
            
            if receiver_telegram:
                telegram_id = receiver_telegram[0]
                self.send_message(telegram_id, "🎉 Тайный Дед Мороз доставил тебе подарок! Приходи в аудиторию 257!")
        
        conn.close()
    
    def notify_gift_received(self, user_db_id):
        """Notify user that their gift was received"""
        conn = sqlite3.connect('santa.db')
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_id FROM users WHERE id = ?", (user_db_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            telegram_id = result[0]
            self.send_message(telegram_id, "🎉 Спасибо! Твой подарок был получен!")
    
    def handle_message(self, chat_id, user_id, user_name, text):
        """Handle regular messages"""
        if user_id in self.user_data:
            step = self.user_data[user_id]["step"]
            
            if step == "fio":
                self.user_data[user_id]["fio"] = text
                self.user_data[user_id]["step"] = "group"
                self.send_message(chat_id, "Отлично! Теперь введи свою учебную группу:")
                
            elif step == "group":
                self.user_data[user_id]["group"] = text
                self.user_data[user_id]["step"] = "preferences"
                self.send_message(chat_id, "Супер! Теперь опиши свои предпочтения:\n• Что ты любишь?\n• Что не любишь?\n• Какие подарки хотел бы получить?")
                
            elif step == "preferences":
                user_info = self.user_data[user_id]
                
                # Save to database
                conn = sqlite3.connect('santa.db')
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "INSERT INTO users (telegram_id, fio, group_name, preferences) VALUES (?, ?, ?, ?)",
                        (user_id, user_info["fio"], user_info["group"], text)
                    )
                    user_db_id = cursor.lastrowid
                    conn.commit()
                    
                    self.send_message(chat_id, f"🎉 Регистрация завершена! 🎉\n\nТвой ID: Тайный Дед Мороз {user_db_id}\nФИО: {user_info['fio']}\nГруппа: {user_info['group']}\n\nЖди начала мероприятия!")
                    logger.info(f"User {user_id} registered as Santa {user_db_id}")
                    
                except sqlite3.IntegrityError:
                    self.send_message(chat_id, "Ты уже зарегистрирован!")
                finally:
                    conn.close()
                
                # Cleanup
                del self.user_data[user_id]
        
        else:
            self.send_message(chat_id, "Используй /start для регистрации!")
    
    def process_updates(self, updates):
        """Process incoming messages"""
        for update in updates:
            self.last_update_id = update["update_id"]
            
            if "message" in update:
                message = update["message"]
                chat_id = message["chat"]["id"]
                user_id = message["from"]["id"]
                user_name = message["from"].get("first_name", "Друг")
                text = message.get("text", "").strip()
                
                logger.info(f"Message from {user_name} ({user_id}): {text}")
                
                # Check if admin command
                if text.startswith("/") and any(text.startswith(cmd) for cmd in ["/stats", "/users", "/close", "/open", "/start_event", "/del", "/gift", "/received", "/help_admin"]):
                    self.handle_admin_commands(chat_id, text, user_id)
                elif text == "/start":
                    self.handle_start(chat_id, user_id, user_name)
                elif text == "/help":
                    help_text = """🎅 Помощь по боту:

/start - регистрация или проверка статуса
/help - эта справка

Для организаторов доступны команды /help_admin"""
                    self.send_message(chat_id, help_text)
                else:
                    self.handle_message(chat_id, user_id, user_name, text)
    
    def run(self):
        """Main bot loop"""
        self.init_database()
        logger.info("Santa Bot started!")
        print("=" * 50)
        print("🎅 Тайный Дед Мороз Бот запущен!")
        print("👥 Обычные команды: /start, /help")
        print("👑 Команды организатора: /help_admin")
        print("⏹️  Для остановки нажмите Ctrl+C")
        print("=" * 50)
        
        empty_responses = 0
        max_empty_responses = 10
        
        while True:
            try:
                updates = self.get_updates()
                
                if updates:
                    empty_responses = 0
                    self.process_updates(updates)
                else:
                    empty_responses += 1
                    if empty_responses >= max_empty_responses:
                        logger.info("No messages for a while, still waiting...")
                        empty_responses = 0
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    
    bot = SimpleSantaBot(BOT_TOKEN)
    bot.run()