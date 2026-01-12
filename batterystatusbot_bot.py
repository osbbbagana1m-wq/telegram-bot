import logging
import requests
import hashlib
import os
import time
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# Налаштування логування
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Дані з Koyeb
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_ID = os.getenv("DEYE_APP_ID")
APP_SECRET = os.getenv("DEYE_APP_SECRET")
EMAIL = os.getenv("DEYE_EMAIL")
PASSWORD = os.getenv("DEYE_PASSWORD")

# ID Станцій
STATION_ID_1 = os.getenv("DEYE_STATION_ID")
STATION_ID_2 = os.getenv("STATION_ID_2")

BASE_URL = "https://eu1-developer.deyecloud.com:443"
BTN_LIFTS = "🔋 Ліфти"
BTN_PUMPS = "🚰 Насоси (ГВП/Опалення)"

# Сервер для Koyeb
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_check():
    port = int(os.getenv("PORT", 8080))
    HTTPServer(('0.0.0.0', port), HealthCheckHandler).serve_forever()

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def get_deye_token():
    url = f"{BASE_URL}/v1.0/account/token?appId={APP_ID}"
    payload = {"appSecret": APP_SECRET, "email": EMAIL, "password": sha256(PASSWORD)}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json().get("accessToken")
    except: return None

def get_battery_soc(station_id):
    token = get_deye_token()
    if not token or not station_id: return None
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/v1.0/station/latest?appId={APP_ID}"
    payload = {"stationId": int(station_id)}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        data = r.json()
        # Повертаємо робочу логіку отримання SOC
        if "batterySOC" in data: return float(data["batterySOC"])
        if "data" in data and "batterySOC" in data["data"]:
            return float(data["data"]["batterySOC"])
        return None
    except: return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[BTN_LIFTS, BTN_PUMPS]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📟 <b>Виберіть систему для перевірки:</b>", reply_markup=reply_markup, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in [BTN_LIFTS, BTN_PUMPS]: return
    
    msg = await update.message.reply_text("🔄 Отримую дані...")
    sid = STATION_ID_1 if text == BTN_LIFTS else STATION_ID_2
    sys_name = "ЛІФТИ" if text == BTN_LIFTS else "НАСОСИ"

    soc = get_battery_soc(sid)
    if soc is None:
        await msg.edit_text(f"❌ Помилка отримання даних для: <b>{sys_name}</b>", parse_mode="HTML")
    else:
        status = "🟢" if soc >= 50 else "🟡" if soc >= 20 else "🔴"
        await msg.edit_text(f"📍 Система: <b>{sys_name}</b>\n{status} <b>Заряд:</b> {soc}%", parse_mode="HTML")

def main():
    Thread(target=run_health_check, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
