from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove
)
from telegram.ext import ContextTypes
from redis_config import redis_client as redis
import json
import os
from dotenv import load_dotenv

load_dotenv()

redis  = redis.redis_client


def is_admin(user_id) -> bool:
    admin_ids = os.getenv("ADMIN_IDS", "")
    admin_ids = [int(x) for x in admin_ids.split(",") if x]
    return user_id in admin_ids

async def get_all_reservations() -> list[dict]:
    ids = await redis.lrange("reservation:requests", 0, -1)

    result = []
    for res_id in ids:
        data = await redis.get(f"reservation:request:{res_id}")
        if data:
            result.append(json.loads(data))

    return result


async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Посмотреть все заявки", callback_data="view_reservations")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выбери действие:",
        reply_markup= markup
    )
    return


def build_pagination_keyboard(current_page, total_pages):
    keyboard = []
    buttons = []

    print(current_page)
    print(total_pages)

    if current_page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page:{current_page-1}"))
    if current_page < total_pages-1:
        buttons.append(InlineKeyboardButton("➡️ Вперед", callback_data=f"page:{current_page+1}"))

    if buttons:
        keyboard.append(buttons)

    return InlineKeyboardMarkup(keyboard)


async def admin_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = 0
    if query.data.startswith("page:"):
        page = int(query.data.split(":")[1])

    reservations = await get_all_reservations()
    per_page = 5

    start = page * per_page
    end = start + per_page
    page_items = reservations[start:end]

    text = "\n\n".join(
        f"📞 {r['phone']} | 🍽 {r['table']} | 📅 {r['date']} {r['time']}" 
        for r in page_items
    ) or "ЗАЯВОК НЕТ"

    total_pages = (len(reservations) + per_page - 1) // per_page
    keyboard = build_pagination_keyboard(page, total_pages)

    await query.edit_message_text(
        text=text,
        reply_markup=keyboard
    )
