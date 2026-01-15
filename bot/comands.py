from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove
)
from telegram.ext import ContextTypes
from redis_config import redis_helpers
from admin.comands import admin_pagination_callback, view_reservation, handle_reservation_decision, update_admin_list
import json, requests, urllib.parse
from redis_config.redis_helpers import get_user_data, set_user_data
from admin.comands import is_admin, admin_start, get_all_reservations, cancel_reservation
from iiko_token.update_token import update_iiko_token
from bot.reminder_mes import schedule_reservation_reminders
from dotenv import load_dotenv
from datetime import date

import os

load_dotenv()

class ReservationBot:
    WEB_APP_URL = os.getenv("WEB_APP_URL")
    IIKO_API_URL = os.getenv("IIKO_API_URL")

    def __init__(self, app):
        self.application = app

    
    async def fetch_tables(self, token: str, terminal_group_id: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "terminalGroupIds": [terminal_group_id],
            "returnSchema": True,
            "revision": 0
        }

        response = requests.post(self.IIKO_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        tables_info = []
        for section in data.get("restaurantSections", []):
            section_info = {
                "id": section["id"],
                "name": section["name"],
                "tables": [
                    {
                        "id": t["id"],
                        "number": t["number"],
                        "seatingCapacity": t["seatingCapacity"],
                        "name": t.get("name", f"Стол {t['number']}"),
                        "x": None,
                        "y": None,
                        "width": None,
                        "height": None
                    }
                    for t in section.get("tables", []) if not t.get("isDeleted", False)
                ]
            }
            if section.get("schema"):
                for table_el in section["schema"].get("tableElements", []):
                    for t in section_info["tables"]:
                        if t["id"] == table_el["tableId"]:
                            t.update({
                                "x": table_el["x"],
                                "y": table_el["y"],
                                "width": table_el["width"],
                                "height": table_el["height"]
                            })
            tables_info.append(section_info)

        return tables_info

    async def fetch_day_reservations(self, date: str):
        token = update_iiko_token(os.getenv("IIKO_KEY"))
        section_id = os.getenv("SECTION_ID")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "restaurantSectionIds": [section_id],
            "dateFrom": f"{date}T00:00:00",
            "dateTo": f"{date}T23:59:59"
        }

        response = requests.post(
            "https://api-ru.iiko.services/api/1/reserve/restaurant_sections_workload",
            json=payload,
            headers=headers
        )

        response.raise_for_status()
        return response.json().get("reserves", [])

    async def delete_msg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msgs = context.user_data.get("delete_msg", [])
        if not isinstance(msgs, list):
            msgs = [msgs]
        for msg_id in msgs:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=msg_id
                )
            except Exception as e:
                print(f"Не удалось удалить сообщение {msg_id}: {e}")

    # -------------------- Start --------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if is_admin(user_id):
            await admin_start(update, context)
            return
        
        await self.delete_msg(update, context)

        keyboard = [
            [InlineKeyboardButton("🍽 Забронировать стол", callback_data="create_reservation")],
            [InlineKeyboardButton("📋 Мои брони", callback_data="my_reservations")]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        # Берём сообщение из update.message или update.callback_query.message
        message = update.message or update.callback_query.message

        text = await message.reply_text(
            "Добро пожаловать! Выберите действие:",
            reply_markup=markup
        )
        context.user_data['delete_msg'] = [text.message_id]


    async def send_welcome_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user = update.effective_user

        data = await get_user_data(user_id)
        data.clear()
        data["name"] = user.first_name
        await set_user_data(user_id, data)

        message = update.message or update.callback_query.message

        await self.delete_msg(update, context)

        delete_msg1 = await message.reply_text(
            "Добро пожаловать!\n\n"
            "Я помогу вам зарезервировать стол.\n"
            "Пожалуйста, заполните данные ниже 👇"
        )
        
        delete_msg2 = await message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(data)
        )

        context.user_data['delete_msg'] = [delete_msg1.message_id, delete_msg2.message_id]


    # -------------------- Клавиатуры --------------------
    def build_keyboard(self, data: dict) -> InlineKeyboardMarkup:
        phone = data.get("phone", "❌ не указан")
        table = data.get("table", "❌ не указан")

        keyboard = [
            [InlineKeyboardButton(f"📱 Номер телефона: {phone}", callback_data="edit_phone")],
            [InlineKeyboardButton(f"🍽 Выбрать стол: {table}", callback_data="edit_table")]
        ]

        if phone != "❌ не указан" and table != "❌ не указан":
            keyboard.append([InlineKeyboardButton("✅ Подтвердить резервацию", callback_data="continue")])

        return InlineKeyboardMarkup(keyboard)

    def phone_keyboard(self) -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [[KeyboardButton("📱 Поделиться номером", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )

    def table_keyboard(self, tables) -> ReplyKeyboardMarkup:
        tables_json = json.dumps(tables)
        encoded_tables = urllib.parse.quote(tables_json)
        url = f"{self.WEB_APP_URL}?tables={encoded_tables}"

        keyboard = [
            [KeyboardButton("Выбрать стол", web_app=WebAppInfo(url=url))]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    

    async def ask_cancel_confirmation(self, update, context, res_id: str):
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_cancel:{res_id}"),
                InlineKeyboardButton("❌ Нет, оставить", callback_data=f"deny_cancel:{res_id}")
            ]
        ]
        markup = InlineKeyboardMarkup(keyboard)

        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            text="⚠️ Вы точно хотите удалить эту бронь?",
            reply_markup=markup
        )
    # -------------------- Callback --------------------
    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        # Для админа
        if is_admin(user_id):
            action = query.data
            if action == "view_reservations" or query.data.startswith("page:"):
                await admin_pagination_callback(update, context)
            
            if action.startswith("reservation:"):
                _, reservation_id, index = action.split(":")
                index = int(index)

                await view_reservation(update, context, reservation_id, index)
            
            if (action.startswith("approve")):
                _, reservation_id = action.split(":")
                await handle_reservation_decision(update, context, reservation_id, True)

            if action.startswith("reject"):
                _, reservation_id = action.split(":")
                await handle_reservation_decision(update, context, reservation_id, False)

        # Для обычного пользователя
        action = query.data
        if action == "create_reservation":
            await self.send_welcome_messages(update, context)
        elif action == "edit_phone":
                await self.edit_phone(update, context)
        elif action == "edit_table":
                await self.edit_table(update, query, context)
        elif action == "continue":
                await self.confirm_reservation(update, query, context)
        elif action == "my_reservations":
             await self.show_user_reservations(update, context)

        elif action.startswith("cancel:"):
            _, res_id = action.split(":")
            await self.ask_cancel_confirmation(update, context, res_id)

        elif action.startswith("confirm_cancel:"):
            _, res_id = action.split(":")
            await cancel_reservation(res_id)
            await redis_helpers.delete_reservation_by_id(res_id)
            await query.edit_message_text("Бронь успешно удалена ✅")
            await self.show_user_reservations(update, context)

        elif action.startswith("deny_cancel"):
            await query.edit_message_text("Отмена удаления броней ❌")
            await self.show_user_reservations(update, context)

        elif action == "back_to_start":
            await self.start(update, context)

    async def edit_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id

        await self.delete_msg(update, context)
        
        data = await get_user_data(user_id)
        data["step"] = "phone"
        await set_user_data(user_id, data)

        delete_msg = await context.bot.send_message(
            chat_id=query.from_user.id,
            text="Укажите ваш номер телефона, нажав на кнопку ⬇️",
            reply_markup=self.phone_keyboard()
    )
        context.user_data['delete_msg'] = delete_msg.message_id



    async def edit_table(self, update: Update, query, context: ContextTypes.DEFAULT_TYPE):
        user_id = query.from_user.id
        await self.delete_msg(update, context)
        
        data = await get_user_data(user_id)
        data["step"] = "table"
        await set_user_data(user_id, data)

        terminal_group_id = os.getenv("TERMINAL_GROUP_ID")
        tables = await self.fetch_tables(update_iiko_token(os.getenv("IIKO_KEY")), terminal_group_id)
        
        delete_msg = await context.bot.send_message(
            chat_id=query.from_user.id,
            text="Нажмите на кнопку для выбора стола ⬇️",
            reply_markup=self.table_keyboard(tables)
        )
        context.user_data['delete_msg'] = delete_msg.message_id

    async def new_reservation_notification(self, reservation_json: str):
        admin_ids = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
        for admin_id in admin_ids:
            view_key = f"admin_view:{admin_id}"
            view = self.application.bot_data.get(view_key)
            
            if view:
                await update_admin_list(self.application, view)

    async def confirm_reservation(self, update: Update, query, context: ContextTypes.DEFAULT_TYPE):
        user_id = query.from_user.id
        data = await get_user_data(user_id)

        await self.delete_msg(update, context)

        reservation_data = {
            "user_id": user_id,
            "name":data["name"],
            "phone": data["phone"],
            "table": data["table"],
            "tableId":data["tableId"],
            "date": data["date"],
            "time": data["time"]
            }
        await redis_helpers.save_reservation(reservation_data)

        await query.message.reply_text(
                    f"✅ Заявка создана:\n"
                    f"📞 Телефон: {data['phone']}\n"
                    f"🍽 Стол: {data['table']}\n"
                    f"📅 Дата: {data['date']}\n"
                    f"🕑 Время: {data['time']}\n\n"
                    f"Дождитесь ответа администратора!"
                )

    # -------------------- Обработчики данных --------------------
    async def number_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        contact = update.message.contact
        if not contact:
            return
        
        user_id = update.effective_user.id

        data = await get_user_data(user_id)

        data["phone"] = contact.phone_number
        data.pop("step", None)
        await set_user_data(user_id, data)

        delete_msg1 = await update.message.reply_text(
            "Телефон сохранён ✅",
            reply_markup=ReplyKeyboardRemove())

        delete_msg2 = await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(data)
        )
        context.user_data['delete_msg'] = [delete_msg1.message_id, delete_msg2.message_id]


    async def web_app_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        data = await get_user_data(user_id)

        web_data = update.message.web_app_data
        payload = json.loads(web_data.data)
        
        print("Данные из WebApp:", payload)
        
        if payload.get("action") == "create_reservation":
            data["tableId"] = payload.get("tableId")
            data["table"] = payload.get("tableNumber")
            data["time"] = payload.get("time")
            data["date"] = payload.get("date")
            await set_user_data(user_id, data)
        
        delete_msg1 = await update.message.reply_text(
        "Стол выбран ✅",
        reply_markup=ReplyKeyboardRemove()
    )

        delete_msg2 = await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(data)
        )
        context.user_data['delete_msg'] = [delete_msg1.message_id, delete_msg2.message_id]


    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        data = await get_user_data(user_id)
        step = data.get("step")
        if not step:
            return

        if step == "phone":
            await update.message.reply_text(
                "Пожалуйста, подтвердите номер через кнопку 📱",
                reply_markup=self.phone_keyboard()
            )
            return

        data.pop("step")
        await set_user_data(user_id, data)
    
    async def show_user_reservations(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        reservations = await get_all_reservations()

        user_reservations = [r for r in reservations if (r["user_id"] == user_id and r["status"] == "CONFIRMED")]
        keyboard1 = []
        keyboard1.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")])
        if not user_reservations:
            text = await query.edit_message_text(
                text="У вас нет активных броней",
                reply_markup=InlineKeyboardMarkup(keyboard1)
            )
            context.user_data['delete_msg'] = [text.message_id]

            return
        
        keyboard = []

        for r in user_reservations:
            button_text = f"📅 {r['date']} {r['time']} 🍽 Стол {r['table']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"noop")])
            keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data=f"cancel:{r['id']}")])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")])

        message = await query.edit_message_text(
            text="Ваши активные брони:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['delete_msg'] = [message.message_id]
