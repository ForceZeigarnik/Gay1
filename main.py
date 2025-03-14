import os
import logging
import sqlite3
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
ADMIN_ID = int(os.getenv('ADMIN_ID', 123456789))
DB_NAME = 'howgay.db'
TEXT_EDIT = range(1)

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_NAME)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                tests_count INTEGER DEFAULT 0,
                last_test DATE
            )''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tests (
                test_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                result INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')
        
        cursor.execute('''
            INSERT OR IGNORE INTO config (key, value)
            VALUES ('main_text', '🌈 Твой показатель: {percentage}%')
        ''')
        self.conn.commit()

    def get_config(self, key):
        cursor = self.conn.cursor()
        cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else None

    def update_config(self, key, value):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO config (key, value)
            VALUES (?, ?)
        ''', (key, value))
        self.conn.commit()

    def add_test_result(self, user_id, username, result):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, tests_count, last_test)
            VALUES (?, ?, COALESCE((SELECT tests_count FROM users WHERE user_id = ?), 0) + 1, CURRENT_TIMESTAMP)
        ''', (user_id, username, user_id))
        
        cursor.execute('''
            INSERT INTO tests (user_id, result)
            VALUES (?, ?)
        ''', (user_id, result))
        
        self.conn.commit()

    def get_stats(self, days):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT AVG(result), COUNT(*)
            FROM tests
            WHERE timestamp >= datetime('now', ?)
        ''', (f'-{days} days',))
        avg, count = cursor.fetchone()
        return round(avg or 0, 1), count or 0

    def get_user_stats(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT tests_count, last_test
            FROM users
            WHERE user_id = ?
        ''', (user_id,))
        return cursor.fetchone()

db = Database()

# Основные обработчики
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    result = random.randint(0, 100)
    db.add_test_result(user.id, user.username, result)
    
    main_text = db.get_config('main_text')
    response_text = main_text.format(percentage=result)
    
    keyboard = [
        [InlineKeyboardButton("🔄 Проверить снова", callback_data='retry')],
        [InlineKeyboardButton("📊 Моя статистика", callback_data='my_stats')]
    ]
    
    await update.message.reply_text(
        response_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_stats(update: Update, period: str):
    periods = {
        'week': 7,
        'month': 30,
        'year': 365
    }
    
    avg, count = db.get_stats(periods[period])
    response = (
        f"📊 Статистика за {period}:\n"
        f"▫️ Средний показатель: {avg}%\n"
        f"▫️ Всего тестов: {count}"
    )
    await update.message.reply_text(response)

async def stats_week(update: Update, context: CallbackContext):
    await handle_stats(update, 'week')

async def stats_month(update: Update, context: CallbackContext):
    await handle_stats(update, 'month')

async def stats_year(update: Update, context: CallbackContext):
    await handle_stats(update, 'year')

# Админ-панель
async def admin_panel(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен!")
        return
    
    keyboard = [
        [InlineKeyboardButton("✏️ Изменить текст", callback_data='edit_text')],
        [InlineKeyboardButton("📊 Полная статистика", callback_data='full_stats')]
    ]
    
    await update.message.reply_text(
        "👑 Админ-панель",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'retry':
        await start(query, context)
    elif query.data == 'my_stats':
        await show_user_stats(query)
    elif query.data == 'edit_text':
        await query.message.reply_text("Введите новый текст (используйте {percentage}):")
        return TEXT_EDIT
    elif query.data == 'full_stats':
        await show_full_stats(query)

async def show_user_stats(query):
    user_id = query.from_user.id
    tests_count, last_test = db.get_user_stats(user_id)
    avg, _ = db.get_stats(365*10)  # Все время
    
    response = (
        "📌 Личная статистика:\n"
        f"▫️ Всего тестов: {tests_count}\n"
        f"▫️ Средний результат: {avg}%\n"
        f"▫️ Последний тест: {last_test.split()[0]}"
    )
    await query.message.reply_text(response)

async def show_full_stats(query):
    stats_data = {
        'week': 7,
        'month': 30,
        'year': 365
    }
    
    response = "📈 Глобальная статистика:\n\n"
    for period, days in stats_data.items():
        avg, count = db.get_stats(days)
        response += (
            f"• {period.capitalize()}:\n"
            f"  ▫️ Среднее: {avg}%\n"
            f"  ▫️ Тестов: {count}\n\n"
        )
    
    await query.message.reply_text(response)

async def update_text(update: Update, context: CallbackContext):
    new_text = update.message.text
    if '{percentage}' not in new_text:
        await update.message.reply_text("❌ В тексте должен быть плейсхолдер {percentage}!")
        return ConversationHandler.END
    
    db.update_config('main_text', new_text)
    await update.message.reply_text("✅ Текст успешно обновлен!")
    return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("🚫 Действие отменено")
    return ConversationHandler.END

def main():
    application = Application.builder().token(os.getenv('BOT_TOKEN')).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('stats_week', stats_week))
    application.add_handler(CommandHandler('stats_month', stats_month))
    application.add_handler(CommandHandler('stats_year', stats_year))
    application.add_handler(CommandHandler('admin', admin_panel))

    # Обработчик кнопок
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            TEXT_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_text)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
