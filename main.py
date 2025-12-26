import os
import asyncio
from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from bot.comands import ReservationBot
from redis_config import redis_helpers

load_dotenv()
TOKEN = os.getenv("TOKEN")


async def start_listener(bot: ReservationBot):
    await redis_helpers.listen_new_reservations(bot.new_reservation_notification)


def main():
    # Создаём приложение
    app = ApplicationBuilder().token(TOKEN).build()

    # Инициализируем бота
    bot = ReservationBot(app)

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.CONTACT, bot.text_handler))
    app.add_handler(MessageHandler(filters.CONTACT, bot.number_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, bot.web_app_handler))

    async def on_startup(app):
        print("Бот успешно инициализирован и запущен")
        asyncio.create_task(start_listener(bot))

    app.post_init = on_startup

    # Запуск бота
    app.run_polling()


if __name__ == "__main__":
    main()
