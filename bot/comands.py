from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove
)
from telegram.ext import ContextTypes
from redis_config import redis_helpers
from admin.comands import admin_pagination_callback, view_reservation, handle_reservation_decision, update_admin_list
import json, requests, urllib.parse
from redis_config.redis_helpers import get_user_data, set_user_data
from admin.comands import is_admin, admin_start
from iiko_token.update_token import update_iiko_token
from dotenv import load_dotenv
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
        user = update.effective_user

        
        if is_admin(user_id):
            await admin_start(update, context)
            return
        
        data = await get_user_data(user_id)

        data.clear()
        
        data["name"] = user.first_name

        await set_user_data(user_id, data)

        delete_msg1 = await update.message.reply_text(
            "Добро пожаловать!\n\n"
            "Я помогу вам зарезервировать стол.\n"
            "Пожалуйста, заполните данные ниже 👇"
        )
        
        delete_msg2 = await update.message.reply_text(
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
        if action == "edit_phone":
            await self.edit_phone(update, context)
        elif action == "edit_table":
            await self.edit_table(update, query, context)
        elif action == "continue":
            await self.confirm_reservation(update, query, context)


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


        res_id = await redis_helpers.save_reservation({
        "user_id": user_id,
        "name":data["name"],
        "phone": data["phone"],
        "table": data["table"],
        "date": data["date"],
        "time": data["time"]
    })



        await query.message.reply_text(
                    f"✅ Резервация подтверждена:\n"
                    f"📞 Телефон: {data['phone']}\n"
                    f"🍽 Стол: {data['table']}\n"
                    f"📅 Дата: {data['date']}\n"
                    f"🕑 Время: {data['time']}\n\n"
                    f"Спасибо за бронирование!"
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