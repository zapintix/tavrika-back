from datetime import datetime, timedelta
from telegram import Update
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from redis_config.redis_helpers import get_reservation_by_id, update_reservation_confirmation

scheduler = AsyncIOScheduler()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def send_confirmation_request(context, reservation):
    print("ЭЭЭЭХХ БЛЯЯЯЯЯЯЯЯЯ")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data=f"confirm_yes:{reservation['id']}"),
            InlineKeyboardButton("❌ Нет", callback_data=f"confirm_no:{reservation['id']}")
        ]
    ])

    msg = await context.bot.send_message(
        chat_id=reservation["user_id"],
        text=(
            "⏰ Напоминание о брони!\n\n"
            f"📅 {reservation['date']} {reservation['time']}\n"
            f"🍽 Стол {reservation['table']}\n\n"
            "Вы точно придёте?"
        ),
        reply_markup=keyboard
    )

    await update_reservation_confirmation(
        reservation["id"],
        status="WAITING",
        message_id=msg.message_id
    )

    scheduler.add_job(
        confirmation_timeout,
        trigger="date",
        run_date=datetime.now() + timedelta(minutes=15),
        args=[context, reservation["id"]],
        misfire_grace_time=60
    )

def schedule_reservation_reminders(context, reservation):
    print("Ждём 5 минут")
    reservation_time = datetime.fromisoformat(
        f"{reservation['date']}T{reservation['time']}"
    )

    confirm_time = reservation_time - timedelta(hours=2)
    run_date = datetime.now() + timedelta(minutes=5)
    if run_date > datetime.now():
        print("ZA:UPA")
        scheduler.add_job(
            send_confirmation_request,
            trigger="date",
            run_date=run_date,
            args=[context, reservation],
            misfire_grace_time=60
        )

async def confirmation_timeout(context, reservation_id):
    from admin.comands import notify_admin_to_call
    reservation = await get_reservation_by_id(reservation_id)
    if not reservation:
        return

    if reservation.get("confirmation_status") == "WAITING":
        await update_reservation_confirmation(reservation_id, "NO_RESPONSE")
        await notify_admin_to_call(context, reservation)


