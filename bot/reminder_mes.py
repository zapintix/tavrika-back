from datetime import datetime, timedelta
from telegram import Update
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
import asyncio

scheduler = AsyncIOScheduler()

async def send_reminder(context, user_id, reservation):
    text = (
        f"⏰ Напоминание о брони!\n"
        f"📅 Дата: {reservation['date']}\n"
        f"🕑 Время: {reservation['time']}\n"
        f"🍽 Стол: {reservation['tableId']}"
    )
    await context.bot.send_message(chat_id=user_id, text=text)

def schedule_reservation_reminders(context, user_id, reservation):
    reservation_time = datetime.fromisoformat(f"{reservation['date']}T{reservation['time']}")

    reminder_1h = reservation_time - timedelta(hours=1)
    if reminder_1h > datetime.now():
        scheduler.add_job(
            send_reminder,
            trigger="date",
            run_date=reminder_1h,
            args=[context, user_id, reservation],
            misfire_grace_time=60 
        )

    reminder_30m = reservation_time - timedelta(minutes=30)
    if reminder_30m > datetime.now():
        scheduler.add_job(
            send_reminder,
            trigger="date",
            run_date=reminder_30m,
            args=[context, user_id, reservation],
            misfire_grace_time=60
        )
