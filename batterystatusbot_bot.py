import logging
import requests
import hashlib
import os
import time
import asyncio
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
STATION_ID_1 = os.getenv("DEYE_STATION_ID")
STATION_ID_2 = os.getenv("STATION_ID_2")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID") # ID каналу/групи для сповіщень

BASE_URL = "https://eu1-developer.deyecloud.com:443"
BTN_LIFTS = "🔋 Ліфти"
BTN_PUMPS = "🚰 Насоси (ГВП/Опалення)"

# Словник для відстеження відправлених сповіщень (щоб не спамити)
sent_alerts = {"LIFTS": set(), "PUMPS": set()}

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
        r = requests.post(url, json=payload, timeout=15)
        return r.json().get("accessToken")
    except: return None

def get_battery_soc(station_id):
    token = get_deye_token()
    if not token or not station_id: return None
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/v1.0/station/latest?appId={APP_ID}"
    payload = {"stationId": int(station_id)}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        data = r.json()
        if "batterySOC" in data: return float(data["batterySOC"])
        if "data" in data and "batterySOC" in data["data"]:
            return float(data["data"]["batterySOC"])
        return None
    except: return None

def format_alert_message(sys_name, soc):
    status_icon = "🟢" if soc > 60 else "🟡" if soc > 30 else "🟠" if soc > 20 else "🔴"
    importance = "⚠️ <b>УВАГА! НИЗЬКИЙ ЗАРЯД</b>" if soc <= 20 else "ℹ️ <b>Інформаційне сповіщення</b>"
    
    return (
        f"{importance}\n\n"
        f"📍 Система: <b>{sys_name}</b>\n"
        f"{status_icon} <b>Заряд батареї: {soc}%</b>\n"
        f"________________\n"
        f"Перевірте стан системи!"
    )

async def check_alerts(app):
    """Фонова задача для перевірки порогів заряду"""
    while True:
        try:
            # Перевірка ЛІФТІВ (50% та 20%)
            soc_lifts = get_battery_soc(STATION_ID_1)
            if soc_lifts is not None:
                for threshold in [50, 20]:
                    if soc_lifts <= threshold and threshold not in sent_alerts["LIFTS"]:
                        await app.bot.send_message(NOTIFY_CHAT_ID, format_alert_message("ЛІФТИ", soc_lifts), parse_mode="HTML")
                        sent_alerts["LIFTS"].add(threshold)
                    elif soc_lifts > threshold + 5: # Скидання прапорця, якщо зарядили
                        sent_alerts["LIFTS"].discard(threshold)

            # Перевірка НАСОСІВ (60% та 20%)
            soc_pumps = get_battery_soc(STATION_ID_2)
            if soc_pumps is not None:
                for threshold in [76, 20]:
                    if soc_pumps <= threshold and threshold not in sent_alerts["PUMPS"]:
                        await app.bot.send_message(NOTIFY_CHAT_ID, format_alert_message("НАСОСИ", soc_pumps), parse_mode="HTML")
                        sent_alerts["PUMPS"].add(threshold)
                    elif soc_pumps > threshold + 5:
                        sent_alerts["PUMPS"].discard(threshold)

        except Exception as e:
            logger.error(f"Alert check error: {e}")
        
        await asyncio.sleep(600) # Перевірка кожні 10 хвилин

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[BTN_LIFTS, BTN_PUMPS]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📟 <b>Виберіть систему:</b>", reply_markup=reply_markup, parse_mode="HTML")

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
        icon = "🟢" if soc >= 50 else "🟡" if soc >= 20 else "🔴"
        await msg.edit_text(f"📍 Система: <b>{sys_name}</b>\n{icon} <b>Заряд:</b> {soc}%", parse_mode="HTML")

def main():
    Thread(target=run_health_check, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запуск фонової перевірки
    loop = asyncio.get_event_loop()
    loop.create_task(check_alerts(app))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
