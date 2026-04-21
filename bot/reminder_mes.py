from __future__ import annotations

from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.max_api import MaxAPIClient
from redis_config.redis_helpers import get_reservation_by_id, get_user_data, update_reservation_confirmation

scheduler = AsyncIOScheduler()


async def send_confirmation_request(context, reservation):
    text = (
        "Напоминание о брони.\n\n"
        f"Дата: {reservation['date']} {reservation['time']}\n"
        f"Стол: {reservation['table']}\n\n"
        "Вы точно придёте?"
    )

    if reservation.get("platform", "telegram") == "max":
        max_client = MaxAPIClient()
        try:
            user_data = await get_user_data(reservation["user_id"])
            chat_id = user_data.get("chat_id")
            response = await max_client.send_message(
                user_id=None if chat_id is not None else reservation["user_id"],
                chat_id=int(chat_id) if chat_id is not None else None,
                text=text,
                attachments=[
                    {
                        "type": "inline_keyboard",
                        "payload": {
                            "buttons": [
                                [
                                    {
                                        "type": "callback",
                                        "text": "Да",
                                        "payload": f"confirm_yes:{reservation['id']}",
                                        "intent": "positive",
                                    },
                                    {
                                        "type": "callback",
                                        "text": "Нет",
                                        "payload": f"confirm_no:{reservation['id']}",
                                        "intent": "negative",
                                    },
                                ]
                            ]
                        },
                    }
                ],
            )
        finally:
            await max_client.close()

        message_id = ((response.get("message") or {}).get("body") or {}).get("mid")
    else:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Да", callback_data=f"confirm_yes:{reservation['id']}"),
                    InlineKeyboardButton("❌ Нет", callback_data=f"confirm_no:{reservation['id']}"),
                ]
            ]
        )
        msg = await context.bot.send_message(
            chat_id=reservation["user_id"],
            text=(
                "⏰ Напоминание о брони!\n\n"
                f"📅 {reservation['date']} {reservation['time']}\n"
                f"🍽 Стол {reservation['table']}\n\n"
                "Вы точно придёте?"
            ),
            reply_markup=keyboard,
        )
        message_id = msg.message_id

    await update_reservation_confirmation(
        reservation["id"],
        status="WAITING",
        message_id=message_id,
    )

    scheduler.add_job(
        confirmation_timeout,
        trigger="date",
        run_date=datetime.now() + timedelta(minutes=15),
        args=[context, reservation["id"]],
        misfire_grace_time=60,
    )


def schedule_reservation_reminders(context, reservation):
    reservation_time = datetime.fromisoformat(f"{reservation['date']}T{reservation['time']}")
    confirm_time = reservation_time - timedelta(hours=2)
    now = datetime.now()
    
    if now > reservation_time:
        print(f"Бронь {reservation['id']} уже была в {reservation_time}, пропускаем напоминание")
        return
    
    minutes_until_reservation = (reservation_time - now).total_seconds() / 60
    
    if minutes_until_reservation < 15:
        print(f"До брони {minutes_until_reservation:.0f} мин, слишком поздно для напоминания")
        run_date = now + timedelta(minutes=5)
        if run_date > reservation_time:
            return
        
    elif confirm_time <= now:
        print(f"Confirm_time {confirm_time} уже прошёл, отправляем через 15 минут")
        run_date = now + timedelta(minutes=15)
        if run_date > reservation_time - timedelta(minutes=5):
            run_date = reservation_time - timedelta(minutes=5)

    else:
        run_date = confirm_time
        print(f"Плановое напоминание в {run_date}")
    
    if run_date <= now:
        print(f"run_date {run_date} уже в прошлом, пропускаем")
        return
    
    scheduler.add_job(
        send_confirmation_request,
        trigger="date",
        run_date=run_date,
        args=[context, reservation],
        misfire_grace_time=60,
    )

async def confirmation_timeout(context, reservation_id):
    from admin.comands import notify_admin_to_call

    reservation = await get_reservation_by_id(reservation_id)
    if not reservation:
        return

    if reservation.get("confirmation_status") == "WAITING":
        await update_reservation_confirmation(reservation_id, "NO_RESPONSE")
        reservation["confirmation_status"] = "NO_RESPONSE"
        await notify_admin_to_call(context, reservation)
