import os
import logging
import random
from datetime import datetime
import aiosqlite
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    InlineQueryHandler
)

# Загрузка переменных окружения
load_dotenv()

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
ADMIN_ID = int(os.getenv('ADMIN_ID'))
BOT_TOKEN = os.getenv('BOT_TOKEN')
DB_NAME = 'howgay.db'
TEXT_EDIT = 1

class Database:
    def __init__(self):
        self.db_name = DB_NAME
        
    async def init_db(self):
        async with aiosqlite.connect(self.db_name) as conn:
            # Создание таблиц
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    tests_count INTEGER DEFAULT 0,
                    last_test DATETIME
                )''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tests (
                    test_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    result INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )''')
            
            # Инициализация текста по умолчанию
            await conn.execute('''
                INSERT OR IGNORE INTO config (key, value)
                VALUES ('main_text', '🌈 Ваш результат: {percentage}%')
            ''')
            await conn.commit()

    async def get_config(self, key):
        async with aiosqlite.connect(self.db_name) as conn:
            cursor = await conn.execute('SELECT value FROM config WHERE key = ?', (key,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def update_config(self, key, value):
        async with aiosqlite.connect(self.db_name) as conn:
            await conn.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, value))
            await conn.commit()

    async def add_test_result(self, user_id, username, result):
        async with aiosqlite.connect(self.db_name) as conn:
            # Обновление данных пользователя
            await conn.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, tests_count, last_test)
                VALUES (?, ?, COALESCE((SELECT tests_count FROM users WHERE user_id = ?), 0) + 1, CURRENT_TIMESTAMP)
            ''', (user_id, username, user_id))
            
            # Добавление результата теста
            await conn.execute('INSERT INTO tests (user_id, result) VALUES (?, ?)', (user_id, result))
            await conn.commit()

    async def get_stats(self, days):
        async with aiosqlite.connect(self.db_name) as conn:
            cursor = await conn.execute('''
                SELECT AVG(result), COUNT(*)
                FROM tests
                WHERE timestamp >= datetime('now', ?)
            ''', (f'-{days} days',))
            avg, count = await cursor.fetchone()
            return round(avg or 0, 1), count or 0

    async def get_user_stats(self, user_id):
        async with aiosqlite.connect(self.db_name) as conn:
            cursor = await conn.execute('SELECT tests_count, last_test FROM users WHERE user_id = ?', (user_id,))
            return await cursor.fetchone()

db = Database()

async def start(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        result = random.randint(0, 100)
        
        await db.add_test_result(user.id, user.username, result)
        main_text = await db.get_config('main_text')
        response_text = main_text.format(percentage=result)
        
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить снова", callback_data='retry')],
            [InlineKeyboardButton("📊 Личная статистика", callback_data='my_stats')],
            [InlineKeyboardButton("🌍 Общая статистика", callback_data='global_stats')]
        ]
        
        await update.message.reply_text(
            response_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Start error: {e}")

async def inline_query(update: Update, context: CallbackContext):
    try:
        user = update.inline_query.from_user
        result = random.randint(0, 100)
        main_text = await db.get_config('main_text')
        response_text = main_text.format(percentage=result)
        
        results = [
            InlineQueryResultArticle(
                id=str(random.getrandbits(64)),
                title="Проверить результат 🌈",
                description="Нажмите чтобы узнать свой процент",
                input_message_content=InputTextMessageContent(
                    f"🔍 Результат для {user.mention_markdown()}:\n{response_text}",
                    parse_mode='Markdown'
                )
            )
        ]
        await update.inline_query.answer(results)
        
    except Exception as e:
        logger.error(f"Inline error: {e}")

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data == 'retry':
            await start(update, context)
        elif query.data == 'my_stats':
            await show_user_stats(query)
        elif query.data == 'global_stats':
            await show_global_stats_menu(query)
            
    except Exception as e:
        logger.error(f"Button handler error: {e}")

async def show_user_stats(query):
    try:
        user_id = query.from_user.id
        stats = await db.get_user_stats(user_id)
        
        if not stats:
            await query.message.reply_text("❌ Вы еще не проходили тест!")
            return
            
        tests_count, last_test = stats
        response = (
            "📌 Ваша статистика:\n"
            f"▫️ Всего проверок: {tests_count}\n"
            f"▫️ Последняя проверка: {last_test.split()[0] if last_test else 'еще не было'}"
        )
        await query.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"User stats error: {e}")

async def show_global_stats_menu(query):
    keyboard = [
        [InlineKeyboardButton("7 дней", callback_data='stats_7')],
        [InlineKeyboardButton("30 дней", callback_data='stats_30')],
        [InlineKeyboardButton("365 дней", callback_data='stats_365')]
    ]
    await query.message.reply_text(
        "🌍 Выберите период статистики:",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_global_stats(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        await query.answer()
        
        days = int(query.data.split('_')[1])
        avg, count = await db.get_stats(days)
        
        await query.message.reply_text(
            f"🌍 Глобальная статистика за {days} дней:\n"
            f"▫️ Средний результат: {avg}%\n"
            f"▫️ Всего проверок: {count}")
            
    except Exception as e:
        logger.error(f"Global stats error: {e}")

async def admin_panel(update: Update, context: CallbackContext):
    try:
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Доступ запрещен!")
            return
        
        keyboard = [
            [InlineKeyboardButton("✏️ Изменить текст", callback_data='edit_text')],
            [InlineKeyboardButton("📈 Общая статистика", callback_data='admin_stats')]
        ]
        await update.message.reply_text(
            "👑 Админ-панель",
            reply_markup=InlineKeyboardMarkup(keyboard))
            
    except Exception as e:
        logger.error(f"Admin panel error: {e}")

async def text_edit_start(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Введите новый текст (используйте {percentage}):")
    return TEXT_EDIT

async def update_text(update: Update, context: CallbackContext):
    try:
        new_text = update.message.text
        if '{percentage}' not in new_text:
            await update.message.reply_text("❌ Текст должен содержать {percentage}!")
            return ConversationHandler.END
        
        await db.update_config('main_text', new_text)
        await update.message.reply_text("✅ Текст успешно обновлен!")
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Update text error: {e}")
        await update.message.reply_text("⚠️ Ошибка при обновлении текста")
        return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("🚫 Действие отменено")
    return ConversationHandler.END

async def init_bot(app):
    await db.init_db()

def main():
    application = Application.builder().token(BOT_TOKEN).post_init(init_bot).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('admin', admin_panel))
    application.add_handler(InlineQueryHandler(inline_query))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(
        handle_global_stats,
        pattern=r'^stats_\d+$'
    ))

    # Обработчик изменения текста
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(text_edit_start, pattern='^edit_text$')],
        states={
            TEXT_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_text)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
