import logging
import time
import hashlib
import requests

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== ЛОГИ ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== DEYE ==================
APP_SECRET = "6afcf4009f601eca123075b848da52f3"
APP_ID = "202601068634010"
EMAIL = "Osbb.bagana1m@gmail.com"
PASSWORD = "M1yDeyabagana1"
STATION_ID = 61747634
BASE_URL = "https://eu1-developer.deyecloud.com"

# ================== TELEGRAM ==================
import os

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
# ================== ЛІМІТ ==================
MAX_CLICKS_PER_HOUR = 4
user_clicks = {}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_deye_token() -> str | None:
    url = f"{BASE_URL}/v1.0/account/token?appId={APP_ID}"
    payload = {
        "appSecret": APP_SECRET,
        "email": EMAIL,
        "password": sha256(PASSWORD),
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        data = r.json()
        return data.get("accessToken")
    except Exception as e:
        logger.error(f"Deye token error: {e}")
        return None


def get_battery_soc() -> float | None:
    token = get_deye_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/v1.0/station/latest?appId={APP_ID}"
    payload = {"stationId": STATION_ID}

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        data = r.json()
        return float(data.get("batterySOC")) if data.get("batterySOC") else None
    except Exception as e:
        logger.error(f"Deye data error: {e}")
        return None


# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["🔋 Рівень батареї | Ліфти"]]
    await update.message.reply_text(
        "Привіт 👋\nНатисни кнопку нижче ⬇️",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text != "🔋 Рівень батареї | Ліфти":
        return

    user_id = update.message.from_user.id
    now = time.time()

    user_clicks.setdefault(user_id, [])
    user_clicks[user_id] = [t for t in user_clicks[user_id] if now - t < 3600]

    if len(user_clicks[user_id]) >= MAX_CLICKS_PER_HOUR:
        await update.message.reply_text("⏳ Ліміт: 4 запити на годину")
        return

    user_clicks[user_id].append(now)

    await update.message.reply_text("⏳ Отримую дані...")

    soc = get_battery_soc()
    if soc is None:
        await update.message.reply_text("❌ Не вдалося отримати дані")
        return

    if soc >= 80:
        status = "🟢 Все чудово"
    elif soc >= 50:
        status = "🟡 Нормально"
    elif soc >= 20:
        status = "🟠 Низький заряд"
    else:
        status = "🔴 Критично"

    await update.message.reply_text(
        f"{status}\n\n🔋 Заряд: <b>{soc}%</b>\n📍 Бажана 1М",
        parse_mode="HTML",
    )


# ================== MAIN ==================
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
