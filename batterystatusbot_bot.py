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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_ID = os.getenv("DEYE_APP_ID")
APP_SECRET = os.getenv("DEYE_APP_SECRET")
EMAIL = os.getenv("DEYE_EMAIL")
PASSWORD = os.getenv("DEYE_PASSWORD")

# Серійні номери інверторів
SN_LIFTS = os.getenv("DEYE_STATION_ID") # Ваш перший серійник (Ліфти)
SN_PUMPS = os.getenv("INVERTER_SN_2")   # Ваш другий серійник (Насоси)

BASE_URL = "https://eu1-developer.deyecloud.com:443"

# ================== CONFIG ==================
MAX_CLICKS_PER_HOUR = 6 # Трохи збільшив, бо тепер дві системи
BTN_LIFTS = "🔋 Ліфти"
BTN_PUMPS = "🚰 Насоси (ГВП/Опалення)"
user_clicks = {}

# ================== HEALTH CHECK SERVER ==================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_check():
    port = int(os.getenv("PORT", 8080))
    httpd = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    httpd.serve_forever()

# ================== HELPERS ==================
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def format_battery_status(soc: float) -> str:
    if soc >= 80: return "🟢 <b>Повний бак</b> — все працює штатно!"
    elif soc >= 50: return "🟡 <b>Норм</b> — енергії достатньо."
    elif soc >= 25: return "🟠 <b>Увага</b> — заряд падає, будьте обачні."
    elif soc >= 15: return "🔴 <b>Критично</b> — обмежте використання!"
    else: return "⚪️ <b>Розряджено</b> — система на межі вимкнення."

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

def get_battery_soc(device_sn: str) -> float | None:
    token = get_deye_token()
    if not token or not device_sn: return None

    headers = {"Authorization": f"Bearer {token}"}
    # Використовуємо запит за серійним номером пристрою
    url = f"{BASE_URL}/v1.0/device/realtime?appId={APP_ID}"
    payload = {"deviceSn": device_sn}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        data = r.json()
        if not data.get("success"): return None
        
        # Шукаємо показник SOC у списку параметрів
        param_list = data.get("data", [])
        for p in param_list:
            if p.get("key") == "batterySoc" or p.get("key") == "soc":
                return float(p.get("value"))
        return None
    except Exception as e:
        logger.error(f"Deye request error: {e}")
        return None

# ================== BOT HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[BTN_LIFTS, BTN_PUMPS]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 <b>Вітаю, сусіди!</b>\n\nВиберіть систему для перевірки заряду:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    if text not in [BTN_LIFTS, BTN_PUMPS]: return
    
    user_id = update.message.from_user.id
    now = time.time()
    user_clicks.setdefault(user_id, [])
    user_clicks[user_id] = [t for t in user_clicks[user_id] if now - t < 3600]

    if len(user_clicks[user_id]) >= MAX_CLICKS_PER_HOUR:
        await update.message.reply_text("⏳ <b>Ліміт запитів вичерпано.</b>\nЗачекайте годину.", parse_mode="HTML")
        return

    user_clicks[user_id].append(now)
    msg = await update.message.reply_text("🔄 Запит до інвертора...")

    # Визначаємо, який серійник використовувати
    target_sn = SN_LIFTS if text == BTN_LIFTS else SN_PUMPS
    system_name = "ЛІФТИ" if text == BTN_LIFTS else "НАСОСИ"

    soc = get_battery_soc(target_sn)
    
    if soc is None:
        await msg.edit_text(f"❌ <b>Помилка</b>\nНе вдалося отримати дані для системи {system_name}.", parse_mode="HTML")
    else:
        await msg.edit_text(
            f"📍 Система: <b>{system_name}</b>\n"
            f"{format_battery_status(soc)}\n\n"
            f"🔋 <b>Заряд:</b> {soc}%",
            parse_mode="HTML"
        )

# ================== MAIN ==================
def main() -> None:
    Thread(target=run_health_check, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🤖 Bot with 2 buttons is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
