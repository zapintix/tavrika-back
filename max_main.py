from __future__ import annotations

import asyncio

import httpx
from dotenv import load_dotenv

from bot.comands import ReservationBot
from bot.max_api import MaxAPIClient
from bot.reminder_mes import scheduler
from redis_config import redis_helpers

load_dotenv()


async def dispatch_update(bot: ReservationBot, update: dict) -> None:
    update_type = update.get("update_type")

    if update_type == "bot_started":
        await bot.handle_bot_started(update)
        return

    if update_type == "message_created":
        await bot.handle_message_created(update)
        return

    if update_type == "message_callback":
        await bot.handle_callback(update)


async def main() -> None:
    client = MaxAPIClient()
    bot = ReservationBot(max_client=client)
    marker = None

    try:
        me = await client.get_me()
        print(me)
        bot.bind_bot_identity(me.get("username"), me.get("user_id"))
    except Exception as exc:
        print(f"Не удалось получить профиль бота: {exc}")

    try:
        await client.set_my_commands(
            [
                {
                    "name": "start",
                    "description": "Открыть главное меню",
                }
            ]
        )
    except Exception as exc:
        print(f"Не удалось обновить команды бота: {exc}")

    if not scheduler.running:
        scheduler.start()

    asyncio.create_task(
        redis_helpers.listen_new_reservations(
            bot.new_reservation_notification
        )
    )

    print("Бот Max запущен")

    try:
        while True:
            try:
                payload = await client.get_updates(
                    marker=marker,
                    types=["bot_started", "message_created", "message_callback"],
                    limit=100,
                    timeout=30,
                )

                updates = payload.get("updates", [])
                for update in updates:
                    try:
                        await dispatch_update(bot, update)
                    except Exception as exc:
                        print(f"Ошибка обработки update {update.get('update_type')}: {exc}")

                marker = payload.get("marker", marker)
            except httpx.HTTPError as exc:
                print(f"Ошибка при long polling Max API: {exc}")
                await asyncio.sleep(5)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
