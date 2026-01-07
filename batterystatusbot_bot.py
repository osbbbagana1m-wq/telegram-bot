import logging
import requests
import hashlib
import time
import os

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

# ================== CONFIG ==================
APP_SECRET = "6afcf4009f601eca123075b848da52f3"
APP_ID = "202601068634010"
EMAIL = "Osbb.bagana1m@gmail.com"
PASSWORD = "M1ybagana1m"
STATION_ID = 61747634
BASE_URL = "https://eu1-developer.deyecloud.com:443"

TELEGRAM_TOKEN = "8466043486:AAHJJkoZnOmlMPop7vNWFpgSTsxXxfFZhLU"

MAX_CLICKS_PER_HOUR = 4
user_clicks = {}

BUTTON_TEXT = "🔋 Рівень батареї | Ліфти"
STATION_NAME = "Бажана 1М"


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
        return "⚪️ <b>Нульовий шанс</b> — все… розходимось."


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
        token = data.get("accessToken")

        if token:
            return token

        logger.error(f"Token error: {data}")
        return None

    except Exception as e:
        logger.error(f"Token exception: {e}")
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

        if not data.get("success"):
            logger.error(f"Station error: {data}")
            return None

        soc = data.get("batterySOC")
        if soc is None:
            return None

        return float(soc)

    except Exception as e:
        logger.error(f"Station exception: {e}")
        return None


# ================== BOT HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[BUTTON_TEXT]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "👋 <b>Вітаю!</b>\n\n"
        "Натисни кнопку нижче, щоб дізнатись рівень батареї.",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


async def get_battery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    now = time.time()

    user_clicks.setdefault(user_id, [])
    user_clicks[user_id] = [t for t in user_clicks[user_id] if now - t < 3600]

    if len(user_clicks[user_id]) >= MAX_CLICKS_PER_HOUR:
        wait = int(3600 - (now - user_clicks[user_id][0])) // 60
        await update.message.reply_text(
            f"⏳ <b>Ліміт вичерпано</b>\n\n"
            f"Спробуй ще раз приблизно через {wait} хв.",
            parse_mode="HTML",
        )
        return

    user_clicks[user_id].append(now)

    await update.message.reply_text("⏳ Отримую дані...")

    soc = get_battery_soc()
    if soc is None:
        await update.message.reply_text(
            "❌ <b>Не вдалось отримати дані з Deye</b>",
            parse_mode="HTML",
        )
        return

    status_text = format_battery_status(soc)

    message = (
        f"{status_text}\n\n"
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
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
