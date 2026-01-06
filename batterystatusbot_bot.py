import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Токен беремо з Environment Variables (Render / локально)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")


# ---------- КНОПКИ ----------
def main_menu():
    keyboard = [
        [InlineKeyboardButton("🔋 Рівень батареї | Ліфти", callback_data="battery")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт 👋\nНатисни кнопку нижче ⬇️",
        reply_markup=main_menu()
    )


# ---------- /battery ----------
async def battery_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔋 Рівень батареї: 85%\n🛗 Ліфти: працюють"
    )


# ---------- ОБРОБКА КНОПКИ ----------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "battery":
        await query.message.reply_text(
            "🔋 Рівень батареї: 85%\n🛗 Ліфти: працюють"
        )


# ---------- ЗАПУСК ----------
def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не встановлений")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("battery", battery_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
