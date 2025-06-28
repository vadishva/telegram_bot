import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.executor import start_webhook
import psycopg2
from dotenv import load_dotenv

# --- 1. Инициализация ---
load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

# Настройки вебхука (Railway автоматически предоставляет URL)
WEBHOOK_HOST = os.getenv("RAILWAY_STATIC_URL", "https://your-project.up.railway.app")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 8000))

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 2. Работа с базой данных ---
class Database:
    def __init__(self):
        self.conn = None
        
    def connect(self):
        try:
            self.conn = psycopg2.connect(DATABASE_URL, sslmode="require")
            logger.info("Успешное подключение к PostgreSQL")
            self._init_db()
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к БД: {e}")
            return False
            
    def _init_db(self):
        with self.conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    date TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
            
    def add_record(self, user_id, name, phone, date):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO records (user_id, name, phone, date) VALUES (%s, %s, %s, %s)",
                    (user_id, name, phone, date)
                )
                self.conn.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления записи: {e}")
            return False
            
    def close(self):
        if self.conn:
            self.conn.close()

db = Database()

# --- 3. Машина состояний (FSM) ---
class RecordStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_date = State()

# --- 4. Обработчики команд ---
@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.answer("📅 Привет! Это бот для записи. Нажмите /register чтобы начать.")

@dp.message_handler(commands=['register'])
async def register_cmd(message: types.Message):
    await message.answer("Введите ваше имя:")
    await RecordStates.waiting_for_name.set()

# --- 5. Обработчики состояний ---
@dp.message_handler(state=RecordStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['name'] = message.text
    await message.answer("📞 Теперь введите ваш номер телефона:")
    await RecordStates.waiting_for_phone.set()

@dp.message_handler(state=RecordStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['phone'] = message.text
    await message.answer("📅 Введите желаемую дату и время (например, 15.07 14:00):")
    await RecordStates.waiting_for_date.set()

@dp.message_handler(state=RecordStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    
    if db.add_record(
        user_id=message.from_user.id,
        name=user_data['name'],
        phone=user_data['phone'],
        date=message.text
    ):
        # Уведомление пользователю
        await message.answer(
            f"✅ Запись успешно оформлена!\n\n"
            f"▪ Имя: {user_data['name']}\n"
            f"▪ Телефон: {user_data['phone']}\n"
            f"▪ Дата: {message.text}\n\n"
            f"Мы свяжемся с вами для подтверждения."
        )
        
        # Уведомление администратору
        await bot.send_message(
            ADMIN_ID,
            f"📌 Новая запись!\n\n"
            f"Клиент: {user_data['name']}\n"
            f"Телефон: {user_data['phone']}\n"
            f"Дата: {message.text}\n"
            f"ID пользователя: {message.from_user.id}"
        )
    else:
        await message.answer("⚠ Произошла ошибка при сохранении записи. Пожалуйста, попробуйте позже.")
    
    await state.finish()

# --- 6. Управление вебхуком ---
async def on_startup(dp):
    if not db.connect():
        logger.error("Не удалось подключиться к базе данных!")
        return
    
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Бот запущен. Вебхук установлен на {WEBHOOK_URL}")

async def on_shutdown(dp):
    logger.warning("Завершение работы...")
    await bot.delete_webhook()
    db.close()
    logger.warning("Бот остановлен")

# --- 7. Запуск приложения ---
if __name__ == '__main__':
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host=WEBAPP_HOST,
        port=WEBAPP_PORT
    )