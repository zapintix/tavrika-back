from telegram.ext import CommandHandler, MessageHandler, ApplicationBuilder, filters, ContextTypes
from bot.comands import start, contact_handler
TOKEN = "8427552505:AAHitPArsns8lMPnJSf3OE2w_Hpdqw775PM"


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))

    print("Бот Запущен")
    app.run_polling()

if __name__ == "__main__":
    main()