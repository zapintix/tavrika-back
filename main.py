from telegram.ext import CommandHandler, MessageHandler, ApplicationBuilder, filters, CallbackQueryHandler
from bot.comands import ReservationBot
from dotenv import load_dotenv
from redis_config import redis_helpers
from bot.reminder_mes import scheduler
import os
import asyncio

load_dotenv()

TOKEN = os.getenv("TOKEN_LOCAL")



def main():
    bot = None
    
    async def post_init(app):
        nonlocal bot
        bot = ReservationBot(app)
        scheduler.start()
        asyncio.create_task(
            redis_helpers.listen_new_reservations(
                bot.new_reservation_notification
            )
        )

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    bot = ReservationBot(app)

    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.CONTACT, bot.text_handler))
    app.add_handler(MessageHandler(filters.CONTACT, bot.number_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot.web_app_handler))

    print("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()

