import logging
import requests
import hashlib
import os
import json
import asyncio
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
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

# Впишіть сюди ваш числовий Telegram ID (якщо хочете отримувати сповіщення адміна по всіх хабах)
ADMIN_CHAT_ID = 5678221647  # Наприклад: 123456789

BASE_URL = "https://eu1-developer.deyecloud.com:443"
BTN_LIFTS = "🔋 Ліфти"
BTN_PUMPS_2 = "🚰 2 контур (Насоси ГВП/Опалення)"
BTN_PUMPS_1 = "🚰 1 контур (Насоси ГВП/Опалення)"
BTN_STOP = "🔕 Зупинити сповіщення"

sent_alerts = {"LIFTS": set(), "PUMPS_2": set(), "PUMPS_1": set()}

USERS_FILE = "subscribers.json"

def load_subscribers():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return set(json.load(f))
        except:
            pass
    return set()

def save_subscribers(subs):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(list(subs), f)
    except Exception as e:
        logger.error(f"Error saving subscribers: {e}")

subscribers = load_subscribers()

grid_state = {
    "is_online": True,
    "outage_start": None,
}

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
    except Exception as e:
        logger.error(f"Token error: {e}")
        return None

def get_station_data(station_id):
    token = get_deye_token()
    if not token or not station_id: return None
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/v1.0/station/latest?appId={APP_ID}"
    payload = {"stationId": int(station_id)}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        data = r.json()
        if "data" in data and isinstance(data["data"], dict):
            return data["data"]
        return data
    except Exception as e:
        logger.error(f"Get station data error: {e}")
        return None

def get_battery_soc(station_id):
    data = get_station_data(station_id)
    if not data: return None
    if "batterySOC" in data and data["batterySOC"] is not None:
        return float(data["batterySOC"])
    return None

async def broadcast_message(app, text, admin_text=None):
    if subscribers:
        for chat_id in list(subscribers):
            try:
                await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Failed to send message to {chat_id}: {e}")
                if "Forbidden" in str(e) or "chat not found" in str(e).lower():
                    subscribers.discard(chat_id)
                    save_subscribers(subscribers)
                    
    if ADMIN_CHAT_ID and admin_text:
        try:
            await app.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send admin message: {e}")

async def check_grid_status(app):
    global grid_state
    monitor_sid = STATION_ID_1
    
    while True:
        try:
            data = get_station_data(monitor_sid)
            if data:
                grid_power = float(data.get("gridPower") or 0)
                purchase_power = float(data.get("purchasePower") or 0)
                soc = data.get("batterySOC")
                
                logger.info(
                    f"Grid Check [Station {monitor_sid}] -> "
                    f"gridPower: {grid_power}W | purchasePower: {purchase_power}W | SOC: {soc}%"
                )
                
                is_currently_online = (grid_power > 0 or purchase_power > 0)
                
                if grid_state["is_online"] and not is_currently_online:
                    grid_state["is_online"] = False
                    grid_state["outage_start"] = asyncio.get_event_loop().time()
                    
                    text = (
                        f"🔴 <b>Світло зникло в будинку!</b>\n"
                        f"Мережева потужність: <b>0 Вт</b>\n"
                        f"Заряд батареї ліфтів: <b>{soc}%</b>"
                    )
                    await broadcast_message(app, text)
                        
                elif not grid_state["is_online"] and is_currently_online:
                    grid_state["is_online"] = True
                    
                    duration_str = ""
                    if grid_state["outage_start"]:
                        duration_sec = asyncio.get_event_loop().time() - grid_state["outage_start"]
                        hours = int(duration_sec // 3600)
                        minutes = int((duration_sec % 3600) // 60)
                        duration_str = f"\n⏱ Було вимкнено: <b>{hours} год {minutes} хв</b>"
                    
                    text = (
                        f"🟢 <b>Світло з'явилося!</b>"
                        f"{duration_str}\n"
                        f"Потужність мережі: <b>{max(grid_power, purchase_power)} Вт</b>"
                    )
                    await broadcast_message(app, text)
        except Exception as e:
            logger.error(f"Grid check exception: {e}")
        
        await asyncio.sleep(120)

async def check_alerts(app):
    while True:
        try:
            # 1. ЛІФТИ (20% для всіх мешканців + адмін)
            soc1 = get_battery_soc(STATION_ID_1)
            if soc1 is not None:
                tr = 20
                if soc1 <= tr and tr not in sent_alerts["LIFTS"]:
                    public_text = f"🔴 <b>УВАГА: ЛІФТИ!</b>\nКритичний розряд батареї: <b>{soc1}%</b>\nЖивлення ліфтів на межі вимкнення."
                    admin_text = f"⚙️ [Адмін] 🔴 <b>ЛІФТИ (Station 1)</b> розрядилися до <b>{soc1}%</b>!"
                    await broadcast_message(app, public_text, admin_text)
                    sent_alerts["LIFTS"].add(tr)
                elif soc1 > tr + 5:
                    sent_alerts["LIFTS"].discard(tr)

            # 2. 2 контур (тільки для адміна)
            soc2 = get_battery_soc(STATION_ID_2)
            if soc2 is not None:
                tr = 20
                if soc2 <= tr and tr not in sent_alerts["PUMPS_2"]:
                    if ADMIN_CHAT_ID:
                        await app.bot.send_message(
                            chat_id=ADMIN_CHAT_ID, 
                            text=f"⚙️ [Адмін] 🔴 <b>2 контур (Насоси)</b> розрядився до <b>{soc2}%</b>!", 
                            parse_mode="HTML"
                        )
                    sent_alerts["PUMPS_2"].add(tr)
                elif soc2 > tr + 5:
                    sent_alerts["PUMPS_2"].discard(tr)

            # 3. 1 контур (тільки для адміна)
            soc3 = get_battery_soc(STATION_ID_3)
            if soc3 is not None:
                tr = 20
                if soc3 <= tr and tr not in sent_alerts["PUMPS_1"]:
                    if ADMIN_CHAT_ID:
                        await app.bot.send_message(
                            chat_id=ADMIN_CHAT_ID, 
                            text=f"⚙️ [Адмін] 🔴 <b>1 контур (Насоси)</b> розрядився до <b>{soc3}%</b>!", 
                            parse_mode="HTML"
                        )
                    sent_alerts["PUMPS_1"].add(tr)
                elif soc3 > tr + 5:
                    sent_alerts["PUMPS_1"].discard(tr)

        except Exception as e:
            logger.error(f"Alert error: {e}")
        await asyncio.sleep(600)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in subscribers:
        subscribers.add(chat_id)
        save_subscribers(subscribers)
        logger.info(f"New subscriber added: {chat_id}")

    keyboard = [
        [BTN_LIFTS],
        [BTN_PUMPS_2],
        [BTN_PUMPS_1],
        [BTN_STOP]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "📟 Вітаємо!\n"
        "Бот моніторить енергосистеми будинку.\n"
        "Ви підписані на аварійні сповіщення про світло та критичний розряд ліфтів.\n\n"
        " 👇 <b>Кнопки нижче</b> дозволяють перевірити поточний заряд систем у будь-який момент.\n"
        " 🔕 Натиснувши кнопку <b>«Зупинити сповіщення»</b> (або ввівши /stop), ви зможете відписатися від розсилки.", 
        reply_markup=reply_markup
    )

async def stop_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        subscribers.discard(chat_id)
        save_subscribers(subscribers)
        logger.info(f"Subscriber removed: {chat_id}")
    
    await update.message.reply_text(
        "🔕 Ви успішно відписалися від сповіщень.\n"
        "Якщо захочете підключитися знову, просто натисніть /start",
        reply_markup=ReplyKeyboardRemove()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text_btn = update.message.text
    
    if text_btn == BTN_STOP:
        await stop_notifications(update, context)
        return

    if text_btn not in [BTN_LIFTS, BTN_PUMPS_2, BTN_PUMPS_1]: 
        return
    
    if chat_id not in subscribers:
        subscribers.add(chat_id)
        save_subscribers(subscribers)
    
    msg = await update.message.reply_text("🔄 Отримую дані...")
    
    if text_btn == BTN_LIFTS:
        sid = STATION_ID_1
    elif text_btn == BTN_PUMPS_2:
        sid = STATION_ID_2
    else:
        sid = STATION_ID_3
        sync_sid = sid # placeholder
        
    soc = get_battery_soc(sid)
    if soc is None:
        await msg.edit_text("❌ Помилка отримання даних")
    else:
        icon = "🟢" if soc >= 50 else "🟡" if soc >= 20 else "🔴"
        await msg.edit_text(f"📍 <b>{text_btn}</b>\n{icon} Заряд: {soc}%", parse_mode="HTML")

async def main_async():
    Thread(target=run_health_check, daemon=True).start()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_notifications))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    asyncio.create_task(check_alerts(app))
    asyncio.create_task(check_grid_status(app))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    stop_signal = asyncio.Event()
    await stop_signal.wait()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
