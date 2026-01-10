# ===== IMPORTS =====
import logging
import requests
import hashlib
import os
import time
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== ENV VARIABLES ==================
# Зчитуємо дані, які ми вказали в панелі Koyeb
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_ID = os.getenv("DEYE_APP_ID")
APP_SECRET = os.getenv("DEYE_APP_SECRET")
EMAIL = os.getenv("DEYE_EMAIL")
PASSWORD = os.getenv("DEYE_PASSWORD")
STATION_ID_RAW = os.getenv("DEYE_STATION_ID")

if not all([TELEGRAM_TOKEN, APP_ID, APP_SECRET, EMAIL, PASSWORD, STATION_ID_RAW]):
    logger.error("❌ Missing one or more Environment Variables!")
    # Не виходимо відразу, щоб Koyeb міг показати лог помилки

STATION_ID = int(STATION_ID_RAW) if STATION_ID_RAW else 0
BASE_URL = "https://eu1-developer.deyecloud.com:443"

# ================== CONFIG ==================
MAX_CLICKS_PER_HOUR = 4
BUTTON_TEXT = "🔋 Рівень батареї | Ліфти"
STATION_NAME = "Бажана 1М"
user_clicks = {}

# ================== HEALTH CHECK SERVER (For Koyeb) ==================
# Це дозволяє Koyeb бачити, що бот живий і не перезапускати його
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_check():
    port = int(os.getenv("PORT", 8080)) # Koyeb автоматично надає порт
    httpd = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"✅ Health Check server started on port {port}")
    httpd.serve_forever()

# ================== HELPERS ==================
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def format_battery_status(soc: float) -> str:
    if soc >= 80: return "🟢 <b>Повний бак</b> — можна літати!"
    elif soc >= 50: return "🟡 <b>Норм</b> — ще можна кататись без паніки."
    elif soc >= 20: return "🟠 <b>Увага</b> — їдемо на честі й божій помочі…"
    elif soc >= 15: return "🔴 <b>Критично</b> — краще пішки. Серйозно."
    else: return "⚪️ <b>Все</b> — вистава закінчена."

# ================== DEYE API ==================
def get_deye_token() -> str | None:
    url = f"{BASE_URL}/v1.0/account/token?appId={APP_ID}"
    payload = {
        "appSecret": APP_SECRET,
        "email": EMAIL,
        "password": sha256(PASSWORD),
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("accessToken")
    except Exception as e:
        logger.error(f"Deye token error: {e}")
        return None

def get_battery_soc() -> float | None:
    token = get_deye_token()
    if not token: return None

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/v1.0/station/latest?appId={APP_ID}"
    payload = {"stationId": STATION_ID}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        data = r.json()
        if not data.get("success"): return None
        
        if "batterySOC" in data: return float(data["batterySOC"])
        if "data" in data and "batterySOC" in data["data"]:
            return float(data["data"]["batterySOC"])
        return None
    except Exception as e:
        logger.error(f"Deye request error: {e}")
        return None

# ================== BOT HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[BUTTON_TEXT]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 <b>Вітаю!</b>\n\nНатисни кнопку, щоб дізнатись рівень батареї.",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text != BUTTON_TEXT: return
    
    user_id = update.message.from_user.id
    now = time.time()
    user_clicks.setdefault(user_id, [])
    user_clicks[user_id] = [t for t in user_clicks[user_id] if now - t < 3600]

    if len(user_clicks[user_id]) >= MAX_CLICKS_PER_HOUR:
        await update.message.reply_text("⏳ <b>Ліміт запитів вичерпано.</b>", parse_mode="HTML")
        return

    user_clicks[user_id].append(now)
    msg = await update.message.reply_text("⏳ Отримую дані...")

    soc = get_battery_soc()
    if soc is None:
        await msg.edit_text("❌ <b>Не вдалося отримати дані</b>", parse_mode="HTML")
    else:
        await msg.edit_text(
            f"{format_battery_status(soc)}\n\n"
            f"🔋 <b>Заряд:</b> {soc}%\n"
            f"📍 <b>Станція:</b> {STATION_NAME}",
            parse_mode="HTML"
        )

# ================== MAIN ==================
def main() -> None:
    # 1. Запускаємо "заглушку" сервера у фоні для Koyeb
    Thread(target=run_health_check, daemon=True).start()

    # 2. Запускаємо самого бота
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
