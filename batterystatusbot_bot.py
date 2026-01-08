# ===== IMPORTS (НА САМОМУ ПОЧАТКУ) =====
import logging
import requests
import hashlib
import os
import time

from telegram import (
    Update,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ===== ENV VARIABLES =====
APP_ID = os.getenv("DEYE_APP_ID")
APP_SECRET = os.getenv("DEYE_APP_SECRET")
EMAIL = os.getenv("DEYE_EMAIL")
PASSWORD = os.getenv("DEYE_PASSWORD")
STATION_ID = int(os.getenv("DEYE_STATION_ID"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== ENV VARIABLES ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_SECRET = os.getenv("DEYE_APP_SECRET")
APP_ID = os.getenv("DEYE_APP_ID")
EMAIL = os.getenv("DEYE_EMAIL")
PASSWORD = os.getenv("DEYE_PASSWORD")

STATION_ID_RAW = os.getenv("DEYE_STATION_ID")
if not STATION_ID_RAW:
    raise RuntimeError("DEYE_STATION_ID is not set in Environment Variables")

STATION_ID = int(STATION_ID_RAW)

BASE_URL = "https://eu1-developer.deyecloud.com:443"

# ================== CONFIG ==================
MAX_CLICKS_PER_HOUR = 4
BUTTON_TEXT = "🔋 Рівень батареї | Ліфти"
STATION_NAME = "Бажана 1М"

user_clicks = {}

# ================== HELPERS ==================
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def format_battery_status(soc: float) -> str:
    if soc >= 80:
        return "🟢 <b>Повний бак</b> — можна літати!"
    elif soc >= 50:
        return "🟡 <b>Норм</b> — ще можна кататись без паніки."
    elif soc >= 20:
        return "🟠 <b>Увага</b> — їдемо на честі й божій помочі…"
    elif soc >= 15:
        return "🔴 <b>Критично</b> — краще пішки. Серйозно."
    else:
        return "⚪️ <b>Все</b> — вистава закінчена."


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
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        data = r.json()

        logger.info(f"Deye RAW response: {data}")

        if not data.get("success"):
            return None

        # 👇 найчастіші варіанти
        if "batterySOC" in data:
            return float(data["batterySOC"])

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


async def get_battery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    now = time.time()

    user_clicks.setdefault(user_id, [])
    user_clicks[user_id] = [t for t in user_clicks[user_id] if now - t < 3600]

    if len(user_clicks[user_id]) >= MAX_CLICKS_PER_HOUR:
        await update.message.reply_text(
            "⏳ <b>Ліміт запитів вичерпано</b>\nСпробуй пізніше.",
            parse_mode="HTML",
        )
        return

    user_clicks[user_id].append(now)
    await update.message.reply_text("⏳ Отримую дані...")

    soc = get_battery_soc()
    if soc is None:
        await update.message.reply_text(
            "❌ <b>Не вдалося отримати дані з Deye</b>",
            parse_mode="HTML",
        )
        return

    message = (
        f"{format_battery_status(soc)}\n\n"
        f"🔋 <b>Заряд:</b> {soc}%\n"
        f"📍 <b>Станція:</b> {STATION_NAME}"
    )

    await update.message.reply_text(message, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.text == BUTTON_TEXT:
        await get_battery(update, context)


# ================== MAIN ==================
def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot started")

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
