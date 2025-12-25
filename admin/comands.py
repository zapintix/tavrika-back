from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import ContextTypes
from redis_config import redis_client as redis
from redis_config.redis_helpers import get_reservation_by_id, delete_reservation_by_id
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

 
def build_pagination_keyboard(current_page, total_pages):
    keyboard = []
    buttons = []

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


    keyboard = []
    for index,  r in enumerate(page_items, start=start):
        button_text = f"👤 {r['name']}\n 📞 {r['phone']}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"reservation:{r['id']}:{index}"
            )
        ])

    total_pages = (len(reservations) + per_page - 1) // per_page
    pagination = build_pagination_keyboard(page, total_pages)

    if pagination.inline_keyboard:
        keyboard.extend(pagination.inline_keyboard)


    await query.edit_message_text(
        text="📋 Заявки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def view_reservation(update: Update, context: ContextTypes.DEFAULT_TYPE, reservation_id, index):
    reservations = await get_all_reservations()
    total = len(reservations)

    data = reservations[index]

    text = (
        f"📋 Заявка {index + 1} из {total}\n\n"
        f"👤 {data['name']}\n"
        f"📞 {data['phone']}\n"
        f"📅 {data['date']} {data['time']}\n"
        f"🍽 Стол {data['table']}\n"
    )

    nav_buttons = []

    if index > 0:
        prev = reservations[index - 1]
        nav_buttons.append(
            InlineKeyboardButton("⬅️", callback_data=f"reservation:{prev['id']}:{index-1}")
        )

    nav_buttons.append(
        InlineKeyboardButton("📋 К списку", callback_data="view_reservations")
    )

    if index < total - 1:
        next_ = reservations[index + 1]
        nav_buttons.append(
            InlineKeyboardButton("➡️", callback_data=f"reservation:{next_['id']}:{index+1}")
        )

    keyboard = [
        nav_buttons,
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"approve:{reservation_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject:{reservation_id}")
        ]
    ]

    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_reservation_decision(update: Update, context: ContextTypes.DEFAULT_TYPE, reservation_id, approved:bool):
    query = update.callback_query
    await query.answer()
    reservation = await get_reservation_by_id(reservation_id)

    if not reservation:
            await query.edit_message_text("❌ Заявка не найдена")
            return

    user_id = reservation["user_id"]


    if approved:
        user_text = (
            "✅ Ваша заявка подтверждена!\n\n"
            f"📅 {reservation['date']} {reservation['time']}\n"
            f"🍽 Стол: {reservation['table']}"
        )

    else:
        user_text = (
            "❌ К сожалению, заявка была отклонена.\n"
            "Попробуйте выбрать другое время."
        )
    
    await delete_reservation_by_id(reservation_id)
    
    await context.bot.send_message(chat_id=user_id, text=user_text)

    await admin_pagination_callback(update, context)