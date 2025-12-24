from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove
)
from telegram.ext import ContextTypes
import json, requests, urllib.parse
from redis_config.redis_helpers import get_user_data, set_user_data, clear_user_data
from iiko_token.update_token import update_iiko_token
from dotenv import load_dotenv
import os

load_dotenv()

class ReservationBot:

    WEB_APP_URL = os.getenv("WEB_APP_URL")
    IIKO_API_URL = os.getenv("IIKO_API_URL")

    def __init__(self):
        pass

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
        print(data)
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

    # -------------------- Start --------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        await clear_user_data(user_id)
        
        data = await get_user_data(user_id)

        data.clear()
        await update.message.reply_text(
            "Добро пожаловать!\n\n"
            "Я помогу вам зарезервировать стол.\n"
            "Пожалуйста, заполните данные ниже 👇"
        )
        await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(data)
        )

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
        action = query.data
        user_id = query.from_user.id

        if action == "edit_phone":
            await self.edit_phone(update, context)
        elif action == "edit_table":
            await self.edit_table(query, context)
        elif action == "continue":
            await self.confirm_reservation(query, context)

    async def edit_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        data = await get_user_data(user_id)
        data["step"] = "phone"
        await set_user_data(user_id, data)

        await query.message.reply_text(
            "Укажите ваш номер телефона, нажав на кнопку ⬇️",
            reply_markup=self.phone_keyboard()
        )

    async def edit_table(self, query, context: ContextTypes.DEFAULT_TYPE):
        user_id = query.from_user.id
        
        data = await get_user_data(user_id)
        data["step"] = "table"
        await set_user_data(user_id, data)

        terminal_group_id = os.getenv("TERMINAL_GROUP_ID")
        tables = await self.fetch_tables(update_iiko_token(os.getenv("IIKO_KEY")), terminal_group_id)
        
        await query.message.reply_text(
            "Нажмите на кнопку для выбора стола ⬇️",
            reply_markup=self.table_keyboard(tables)
        )

    async def confirm_reservation(self, query, context: ContextTypes.DEFAULT_TYPE):
        user_id = query.from_user.id
        data = await get_user_data(user_id)
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

        await update.message.reply_text("Телефон сохранён ✅", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(data)
        )

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
        
        await update.message.reply_text(
            f"Стол {payload.get('tableNumber')} выбран ✅",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(data)
        )

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
        await update.message.reply_text(
            "Данные обновлены ✅",
            reply_markup=self.build_keyboard(data)
        )
