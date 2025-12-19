from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove
)
from telegram.ext import ContextTypes
import json, requests, urllib.parse

class ReservationBot:
    WEB_APP_URL = "https://hgq64vxn-8002.euw.devtunnels.ms/test"

    IIKO_API_URL = "https://api-ru.iiko.services/api/1/reserve/available_restaurant_sections"

    def __init__(self):
        pass


    async def fetch_tables(self, token:str, terminal_group_id:str):
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

    # -------------------- Start --------------------
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.clear()
        await update.message.reply_text(
            "Добро пожаловать!\n\n"
            "Я помогу вам зарезервировать стол.\n"
            "Пожалуйста, заполните данные ниже 👇"
        )
        await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(context.user_data)
        )

    # -------------------- Клавиатуры --------------------
    def build_keyboard(self, data: dict) -> InlineKeyboardMarkup:
        phone = data.get("phone", "❌ не указан")
        table = data.get("table", "❌ не указан")
        guests = data.get("guests", "❌ не указано")

        keyboard = [
            [InlineKeyboardButton(f"Ввести номер телефона: {phone}", callback_data="edit_phone")],
            [InlineKeyboardButton(f"Указать кол-во гостей: {guests}", callback_data="edit_guests")],
            [InlineKeyboardButton(f"Выбрать стол: {table}", callback_data="edit_table")]
        ]

        if phone != "❌ не указан" and table != "❌ не указан" and guests != "❌ не указано":
            keyboard.append([InlineKeyboardButton("➡️ Продолжить резервацию", callback_data="continue")])

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
        return ReplyKeyboardMarkup(
            [[KeyboardButton(
            text="Выбрать стол",
            web_app=WebAppInfo(url=url)
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    # -------------------- Callback --------------------
    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action = query.data

        if action == "edit_phone":
            await self.edit_phone(query, context)
        elif action == "edit_guests":
            await self.edit_guests(query, context)
        elif action == "edit_table":
            await self.edit_table(query, context)
        elif action == "continue":
            await self.confirm_reservation(query, context)

    async def edit_phone(self, query, context):
        context.user_data["step"] = "phone"
        await query.message.reply_text(
            "Укажите ваш номер телефона, нажав на кнопку ⬇️",
            reply_markup=self.phone_keyboard()
        )

    async def edit_guests(self, query, context):
        context.user_data["step"] = "guests"
        await query.message.edit_text("Введите количество гостей:")

    async def edit_table(self, query, context):
        context.user_data["step"] = "table"
        iiko_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJBcGlMb2dpbklkIjoiMzFlNmE4OTAtNGY3My00MmM0LWFiNzQtMjJhN2ExMTU1OTgzIiwibmJmIjoxNzY2MTM3ODM0LCJleHAiOjE3NjYxNDE0MzQsImlhdCI6MTc2NjEzNzgzNCwiaXNzIjoiaWlrbyIsImF1ZCI6ImNsaWVudHMifQ.7aV_a-s1ZntQZ-VcWpNqVo_jybeS-YvjjsEsPb4Aluk"
        terminal_group_id = "6c03d026-3597-afab-0194-600d43c50065"
        tables = await self.fetch_tables(iiko_token, terminal_group_id)
        await query.message.reply_text(
            "Нажмите на кнопку для выбора стола ⬇️",
            reply_markup=self.table_keyboard(tables)
        )

    async def confirm_reservation(self, query, context):
        await query.message.edit_text(
            f"✅ Резервация подтверждена:\n"
            f"📞 {context.user_data['phone']}\n"
            f"🍽 Стол {context.user_data['table']}\n"
            f"👥 {context.user_data['guests']} гостей"
        )

    # -------------------- Обработчики данных --------------------
    async def number_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        contact = update.message.contact
        if contact:
            context.user_data["phone"] = contact.phone_number
            context.user_data.pop("step", None)
            await update.message.reply_text("Телефон сохранён ✅", reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text(
                "Выберите, что хотите указать:",
                reply_markup=self.build_keyboard(context.user_data)
            )

    async def web_app_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        web_data = update.message.web_app_data
        payload = json.loads(web_data.data)

        if payload.get("action") == "select_table":
            context.user_data["table"] = payload.get("tableId")

        await update.message.reply_text(
            f"Стол {payload.get('tableId')} выбран ✅",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text(
            "Выберите, что хотите указать:",
            reply_markup=self.build_keyboard(context.user_data)
        )

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        step = context.user_data.get("step")
        if not step:
            return

        value = update.message.text.strip()

        if step == "phone":
            await update.message.reply_text(
                "Пожалуйста, подтвердите номер через кнопку 📱",
                reply_markup=self.phone_keyboard()
            )
            return

        elif step == "guests":
            if not value.isdigit() or int(value) <= 0:
                await update.message.reply_text("❌ Введите корректное кол-во гостей")
                return
            if int(value) > 6:
                await update.message.reply_text("❌ Стол не выдержит больше 6 гостей")
                return
            context.user_data["guests"] = value

        context.user_data.pop("step")
        await update.message.reply_text(
            "Данные обновлены ✅",
            reply_markup=self.build_keyboard(context.user_data)
        )
