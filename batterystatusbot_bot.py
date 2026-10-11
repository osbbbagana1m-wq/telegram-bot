import logging
import requests
import hashlib
import os
import asyncio
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ENV
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_ID = os.getenv("DEYE_APP_ID")
APP_SECRET = os.getenv("DEYE_APP_SECRET")
EMAIL = os.getenv("DEYE_EMAIL")
PASSWORD = os.getenv("DEYE_PASSWORD")
STATION_ID_1 = os.getenv("DEYE_STATION_ID")
STATION_ID_2 = os.getenv("DEYE_STATION_ID_2")
STATION_ID_3 = os.getenv("DEYE_STATION_ID_3")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID")

# ID ТЕМИ: Теплопостачання/Електрика
THREAD_ID = 12813 

BASE_URL = "https://eu1-developer.deyecloud.com:443"
BTN_LIFTS = "🔋 Ліфти"
BTN_PUMPS_2 = "🚰 2 контур (Насоси ГВП/Опалення)"
BTN_PUMPS_1 = "🚰 1 контур (Насоси ГВП/Опалення)"

sent_alerts = {"LIFTS": set(), "PUMPS_2": set(), "PUMPS_1": set()}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_health_check():
    port = int(os.getenv("PORT", 10000))
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

async def check_alerts(app):
    while True:
        if NOTIFY_CHAT_ID and "-" in str(NOTIFY_CHAT_ID):
            try:
                # 1. ЛІФТИ (50, 20)
                soc1 = get_battery_soc(STATION_ID_1)
                if soc1 is not None:
                    for tr in [50, 20]:
                        if soc1 <= tr and tr not in sent_alerts["LIFTS"]:
                            text = f"⚠️ <b>ЛІФТИ</b>\n{'🟡' if tr==50 else '🔴'} Заряд: <b>{soc1}%</b>"
                            await app.bot.send_message(NOTIFY_CHAT_ID, text, message_thread_id=THREAD_ID, parse_mode="HTML")
                            sent_alerts["LIFTS"].add(tr)
                        elif soc1 > tr + 5: sent_alerts["LIFTS"].discard(tr)

                # 2. 2 контур (50, 20)
                soc2 = get_battery_soc(STATION_ID_2)
                if soc2 is not None:
                    for tr in [50, 20]:
                        if soc2 <= tr and tr not in sent_alerts["PUMPS_2"]:
                            text = f"⚠️ <b>2 контур (Насоси ГВП/Опалення)</b>\n{'🟡' if tr==50 else '🔴'} Заряд: <b>{soc2}%</b>"
                            await app.bot.send_message(NOTIFY_CHAT_ID, text, message_thread_id=THREAD_ID, parse_mode="HTML")
                            sent_alerts["PUMPS_2"].add(tr)
                        elif soc2 > tr + 5: sent_alerts["PUMPS_2"].discard(tr)

                # 3. 1 контур (50, 20)
                soc3 = get_battery_soc(STATION_ID_3)
                if soc3 is not None:
                    for tr in [50, 20]:
                        if soc3 <= tr and tr not in sent_alerts["PUMPS_1"]:
                            text = f"⚠️ <b>1 контур (Насоси ГВП/Опалення)</b>\n{'🟡' if tr==50 else '🔴'} Заряд: <b>{soc3}%</b>"
                            await app.bot.send_message(NOTIFY_CHAT_ID, text, message_thread_id=THREAD_ID, parse_mode="HTML")
                            sent_alerts["PUMPS_1"].add(tr)
                        elif soc3 > tr + 5: sent_alerts["PUMPS_1"].discard(tr)

            except Exception as e: logger.error(f"Alert error: {e}")
        await asyncio.sleep(600)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [BTN_LIFTS],
        [BTN_PUMPS_2],
        [BTN_PUMPS_1]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("📟 Виберіть систему:", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_btn = update.message.text
    if text_btn not in [BTN_LIFTS, BTN_PUMPS_2, BTN_PUMPS_1]: return
    
    msg = await update.message.reply_text("🔄 Отримую дані...")
    
    if text_btn == BTN_LIFTS:
        sid = STATION_ID_1
    elif text_btn == BTN_PUMPS_2:
        sid = STATION_ID_2
    else:
        sid = STATION_ID_3
        
    soc = get_battery_soc(sid)
    if soc is None: await msg.edit_text("❌ Помилка отримання даних")
    else:
        icon = "🟢" if soc >= 50 else "🟡" if soc >= 20 else "🔴"
        await msg.edit_text(f"📍 <b>{text_btn}</b>\n{icon} Заряд: {soc}%", parse_mode="HTML")

async def main_async():
    Thread(target=run_health_check, daemon=True).start()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    asyncio.create_task(check_alerts(app))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    stop_signal = asyncio.Event()
    await stop_signal.wait()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
