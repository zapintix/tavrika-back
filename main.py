from telegram.ext import CommandHandler, MessageHandler, ApplicationBuilder, filters, CallbackQueryHandler
from bot.comands import ReservationBot
from dotenv import load_dotenv
from admin.comands import admin_pagination_callback
import os

load_dotenv()

TOKEN = os.getenv("TOKEN")


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