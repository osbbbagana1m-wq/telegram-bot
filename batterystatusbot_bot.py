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

# Стан для моніторингу світла
grid_state = {
    "is_online": True,
    "outage_start": None,
    "consecutive_offline": 0,
    "consecutive_online": 0,
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
    except: return None

def get_station_data(station_id):
    """Отримує повний словник даних станції з Deye Cloud для аналізу SoC та мережі."""
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
    except: return None

def get_battery_soc(station_id):
    data = get_station_data(station_id)
    if not data: return None
    if "batterySOC" in data: return float(data["batterySOC"])
    return None

async def check_grid_status(app):
    """Фонова перевірка світла: базовий інтервал 2 хв, при підозрі — контрольна перевірка через 1 хв."""
    global grid_state
    monitor_sid = STATION_ID_1  # Використовуємо першу станцію як базову для контролю мережі
    
    while True:
        try:
            data = get_station_data(monitor_sid)
            if data:
                grid_voltage = float(data.get("gridVoltage", data.get("grid_voltage", 220)))
                is_grid_present = grid_voltage > 170
                
                if not is_grid_present:
                    grid_state["consecutive_offline"] += 1
                    grid_state["consecutive_online"] = 0
                    
                    # Якщо виявили зникнення вперше, робимо швидку перевірку через 1 хв
                    if grid_state["consecutive_offline"] == 1:
                        await asyncio.sleep(60)
                        continue
                        
                    # Якщо підтвердилося (1 швидка + 1 основна перевірка)
                    if grid_state["consecutive_offline"] >= 2 and grid_state["is_online"]:
                        grid_state["is_online"] = False
                        grid_state["outage_start"] = asyncio.get_event_loop().time()
                        
                        if NOTIFY_CHAT_ID and "-" in str(NOTIFY_CHAT_ID):
                            text = f"🔴 <b>Світло зникло в будинку!</b>\n(Мережа зникла, напруга: {grid_voltage}В)"
                            await app.bot.send_message(NOTIFY_CHAT_ID, text, message_thread_id=THREAD_ID, parse_mode="HTML")
                else:
                    grid_state["consecutive_online"] += 1
                    grid_state["consecutive_offline"] = 0
                    
                    # Якщо світло з'явилося стабільно (2 перевірки поспіль)
                    if grid_state["consecutive_online"] >= 2 and not grid_state["is_online"]:
                        grid_state["is_online"] = True
                        
                        duration_str = ""
                        if grid_state["outage_start"]:
                            duration_sec = asyncio.get_event_loop().time() - grid_state["outage_start"]
                            hours = int(duration_sec // 3600)
                            minutes = int((duration_sec % 3600) // 60)
                            duration_str = f"\n⏱ Було вимкнено: <b>{hours} год {minutes} хв</b>"
                        
                        if NOTIFY_CHAT_ID and "-" in str(NOTIFY_CHAT_ID):
                            text = f"🟢 <b>Світло з'явилося!</b>{duration_str}"
                            await app.bot.send_message(NOTIFY_CHAT_ID, text, message_thread_id=THREAD_ID, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Grid check error: {e}")
        
        # Стандартний інтервал перевірки — 2 хвилини
        await asyncio.sleep(120)

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
                        if soc2 <= tr and
