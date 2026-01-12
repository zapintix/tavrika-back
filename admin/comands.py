from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import ContextTypes
from redis_config import redis_client as redis
from redis_config.redis_helpers import get_reservation_by_id,update_reservation_status,  delete_reservation_by_id, get_user_data
from iiko_token.update_token import update_iiko_token
import json, os, httpx, uuid
from datetime import datetime
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
            reservation = json.loads(data)
            if reservation.get("status") == "PENDING":
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

async def update_admin_list(application, view):
        reservations = await get_all_reservations()
        per_page = 5
        page = view["page"]

        start = page * per_page
        end = start + per_page
        page_items = reservations[start:end]

        keyboard = []
        for index, r in enumerate(page_items, start=start):
            button_text = f"👤 {r['name']}\n📞 {r['phone']}"
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"reservation:{r['id']}:{index}"
                )
            ])

        if not page_items:
            keyboard.append([InlineKeyboardButton("❌ Заявок нет", callback_data="noop")])

        total_pages = (len(reservations) + per_page - 1) // per_page
        pagination = build_pagination_keyboard(page, total_pages)
        if pagination.inline_keyboard:
            keyboard.extend(pagination.inline_keyboard)

        await application.bot.edit_message_text(
            chat_id=view["chat_id"],
            message_id=view["message_id"],
            text="📋 Заявки:",
            reply_markup=InlineKeyboardMarkup(keyboard)
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

    if not page_items:
            print(page_items)
            keyboard.append([
        InlineKeyboardButton("❌ Заявок нет", callback_data="noop")
    ])
            
    total_pages = (len(reservations) + per_page - 1) // per_page
    pagination = build_pagination_keyboard(page, total_pages)

    if pagination.inline_keyboard:
        keyboard.extend(pagination.inline_keyboard)


    await query.edit_message_text(
        text="📋 Заявки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    admin_id = query.from_user.id
    view = context.application.bot_data[f"admin_view:{admin_id}"] = {
        "chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
        "page": page
    }

    print("Данные страницы админа: ",view)

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

def format_phone(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    if digits.startswith("8"):
        digits = "7" + digits[1:]
    return "+" + digits

async def create_reserve(reservation_data: dict):
    token = update_iiko_token(os.getenv("IIKO_KEY"))
    reserve_id = str(uuid.uuid4())
    external_number = f"RES-{reserve_id[:8]}"

    dt = datetime.fromisoformat(f"{reservation_data['date']}T{reservation_data['time']}")
    iso_date = dt.isoformat()

    body = {
        "organizationId": os.getenv("ORGANIZATION_ID"),
        "terminalGroupId": os.getenv("TERMINAL_GROUP_ID"),
        "externalNumber": external_number,
        "customer": {
            "name": reservation_data["name"],
            "type": "one-time"
        },
        "phone": format_phone(reservation_data["phone"]),
        "guestsCount": reservation_data.get("guests_count", 2),
        "comment": "TEST запрос",
        "durationInMinutes": 120,
        "shouldRemind": True,
        "tableIds": [reservation_data["table_id"]],
        "estimatedStartTime": iso_date,
        "eventType": reservation_data.get("eventType", "telegram_bot")
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}" 
    }

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(os.getenv("IIKO_CREATE_URL"), headers=headers, json=body)

    if r.status_code != 200:
        return {"Status": "error", "iiko_response": r.text}

    return {"status": "created", "reserve_id": reserve_id, "iiko": r.json()}   

async def handle_reservation_decision(update: Update, context: ContextTypes.DEFAULT_TYPE, reservation_id, approved:bool):
    query = update.callback_query
    await query.answer()
    reservation = await get_reservation_by_id(reservation_id)

    if not reservation:
            await query.edit_message_text("❌ Заявка не найдена")
            return

    user_id = reservation["user_id"]

    data = await get_user_data(user_id)

    if approved:
        user_text = (
            "✅ Ваша заявка подтверждена!\n\n"
            f"📅 {reservation['date']} {reservation['time']}\n"
            f"🍽 Стол: {reservation['table']}"
        )

        reservation_result = await create_reserve({
        "name": data["name"],
        "phone": data["phone"],
        "table_id": data["tableId"],
        "date": data["date"],
        "time": data["time"]
        })

        print(reservation_result)
        await update_reservation_status(reservation_id, "CONFIRMED")


    else:
        user_text = (
            "❌ К сожалению, заявка была отклонена.\n"
            "Попробуйте выбрать другое время."
        )
        await update_reservation_status(reservation_id, "CANCELED")
        
    await context.bot.send_message(chat_id=user_id, text=user_text)

    await admin_pagination_callback(update, context)