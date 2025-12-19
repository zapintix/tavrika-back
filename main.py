from telegram.ext import CommandHandler, MessageHandler, ApplicationBuilder, filters, CallbackQueryHandler
from bot.comands import ReservationBot
TOKEN = "8328702156:AAH_aRdk-2uFIgM7gdkSR1dhBzH3vKTUSOI"


def main():
    bot = ReservationBot()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.CONTACT, bot.text_handler))
    app.add_handler(MessageHandler(filters.CONTACT, bot.number_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot.web_app_handler))


    print("Бот Запущен")
    app.run_polling()

if __name__ == "__main__":
    main()