import requests
import json
import os
import time
from dotenv import load_dotenv
from bot.comands import ReservationBot  # Import the original bot logic
from redis_config import redis_helpers
from datetime import datetime, timedelta
import asyncio
from admin.comands import is_admin

load_dotenv()

MAX_API_URL = "https://platform-api.max.ru"
MAX_TOKEN = os.getenv("MAX_TOKEN")  # Assume MAX_TOKEN is set in .env

class MaxReservationBot(ReservationBot):
    def __init__(self):
        super().__init__()
        self.headers = {
            "Authorization": f"Bearer {MAX_TOKEN}",
            "Content-Type": "application/json"
        }

    def send_message(self, chat_id, text, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "text": text
        }
        if reply_markup:
            attachments = [self.build_inline_keyboard(reply_markup)]
            payload["attachments"] = attachments

        response = requests.post(f"{MAX_API_URL}/messages", json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def send_photo(self, chat_id, photo_url, caption, reply_markup=None):
        # Implement if needed
        pass

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        # Implement if needed
        pass

    def answer_callback_query(self, callback_query_id, text=None):
        # Implement if needed
        pass

    def build_inline_keyboard(self, buttons):
        """Convert Telegram-style buttons to MaX inline_keyboard"""
        keyboard = []
        for row in buttons:
            keyboard_row = []
            for button in row:
                max_button = {
                    "type": "callback",
                    "text": button.text,
                    "payload": button.callback_data
                }
                keyboard_row.append(max_button)
            keyboard.append(keyboard_row)

        return {
            "type": "inline_keyboard",
            "payload": {
                "buttons": keyboard
            }
        }

    # Adapt the start method
    async def start(self, chat_id, user_id):
        if is_admin(user_id):
            # Handle admin start - need to adapt admin logic
            pass
        else:
            keyboard = [
                [{"text": "🍽 Забронировать стол", "callback_data": "create_reservation"}],
                [{"text": "📋 Мои брони", "callback_data": "my_reservations"}]
            ]
            attachments = [self.build_inline_keyboard(keyboard)]

            self.send_message(chat_id, "Добро пожаловать в Таврику. Что бы вы хотели?", attachments)

    def handle_callback(self, chat_id, user_id, callback_data):
        # Parse callback_data and call appropriate methods
        if callback_data == "create_reservation":
            self.resolve_booking_target(chat_id)
        elif callback_data == "my_reservations":
            asyncio.run(self.reservations(chat_id, user_id))
        elif callback_data == "me":
            asyncio.run(self.send_welcome_messages(chat_id, user_id, False))
        elif callback_data == "other_people":
            asyncio.run(self.send_welcome_messages(chat_id, user_id, True))
        elif callback_data == "edit_name":
            self.edit_name(chat_id, user_id)
        elif callback_data == "edit_phone":
            self.edit_phone(chat_id, user_id)
        elif callback_data == "edit_table":
            self.edit_table(chat_id, user_id)
        elif callback_data == "continue":
            asyncio.run(self.confirm_reservation(chat_id, user_id))
        # Add more handlers...

    def edit_name(self, chat_id, user_id):
        # Set state to waiting for name
        asyncio.run(self.set_user_state(user_id, "waiting_name"))
        self.send_message(chat_id, "Пожалуйста, введите имя:")

    def edit_phone(self, chat_id, user_id):
        asyncio.run(self.set_user_state(user_id, "waiting_phone"))
        self.send_message(chat_id, "Пожалуйста, введите номер телефона:")

    def edit_table(self, chat_id, user_id):
        # For simplicity, show table selection - but need to implement
        self.send_message(chat_id, "Выбор стола пока не реализован. Используйте веб-приложение.")

    async def set_user_state(self, user_id, state):
        data = await redis_helpers.get_user_data(user_id)
        data["state"] = state
        await redis_helpers.set_user_data(user_id, data)

    async def confirm_reservation(self, chat_id, user_id):
        # Implement confirmation logic
        self.send_message(chat_id, "Бронь подтверждена!")  # Placeholder

    async def reservations(self, chat_id, user_id):
        # Placeholder
        self.send_message(chat_id, "Ваши брони: (пока не реализовано)")

    def resolve_booking_target(self, chat_id):
        keyboard = [
            [{"text": "На себя", "callback_data": "me"}],
            [{"text": "На другого человека", "callback_data": "other_people"}]
        ]
        attachments = [self.build_inline_keyboard(keyboard)]
        self.send_message(chat_id, "На кого бронируем стол?", attachments)

    async def send_welcome_messages(self, chat_id, user_id, other_people):
        data = await redis_helpers.get_user_data(user_id)
        data.clear()
        data["for_another_person"] = other_people

        if not other_people:
            # In MaX, we don't have user info like Telegram, so ask for name
            data["name"] = "Укажите имя"

        await redis_helpers.set_user_data(user_id, data)

        self.send_message(chat_id, "Я помогу вам зарезервировать стол.\nПожалуйста, заполните данные ниже 👇")
        
        # Build keyboard - need to adapt build_keyboard
        keyboard = self.build_keyboard(data)
        attachments = [self.build_inline_keyboard(keyboard)]
        self.send_message(chat_id, "Пожалуйста, укажите:", attachments)

    def build_keyboard(self, data):
        # Adapted from original
        for_another_person = data.get("for_another_person", False)
        keyboard = []

        if for_another_person:
            name = data.get("name", "Укажите имя гостя")
            keyboard.append([{"text": f"👤 {name}", "callback_data": "edit_name"}])

        phone = data.get("phone", "Укажите номер телефона")
        table = f"Ваш стол: № {data['table']}" if "table" in data else "Выберите стол"

        keyboard.append([{"text": f"📱 {phone}", "callback_data": "edit_phone"}])
        keyboard.append([{"text": f"🍽 {table}", "callback_data": "edit_table"}])

        if phone != "Укажите номер телефона" and table != "Выберите стол":
            if not for_another_person or data.get("name"):
                keyboard.append([{"text": "✅ Подтвердить бронь", "callback_data": "continue"}])

        return keyboard

    async def handle_text(self, chat_id, user_id, text):
        data = await redis_helpers.get_user_data(user_id)
        state = data.get("state")

        if state == "waiting_name":
            data["name"] = text
            data["state"] = None
            await redis_helpers.set_user_data(user_id, data)
            self.send_message(chat_id, f"Имя установлено: {text}")
            # Resend the keyboard
            keyboard = self.build_keyboard(data)
            attachments = [self.build_inline_keyboard(keyboard)]
            self.send_message(chat_id, "Пожалуйста, укажите:", attachments)
        elif state == "waiting_phone":
            data["phone"] = text
            data["state"] = None
            await redis_helpers.set_user_data(user_id, data)
            self.send_message(chat_id, f"Телефон установлен: {text}")
            keyboard = self.build_keyboard(data)
            attachments = [self.build_inline_keyboard(keyboard)]
            self.send_message(chat_id, "Пожалуйста, укажите:", attachments)
    async def handle_text(self, chat_id, user_id, text):
        data = await redis_helpers.get_user_data(user_id)
        state = data.get("state")

        if state == "waiting_name":
            data["name"] = text
            await redis_helpers.set_user_data(user_id, data)
            self.send_message(chat_id, f"Имя установлено: {text}")
            keyboard = self.build_keyboard(data)
            attachments = [self.build_inline_keyboard(keyboard)]
            self.send_message(chat_id, "Пожалуйста, укажите:", attachments)
        elif state == "waiting_phone":
            data["phone"] = text
            await redis_helpers.set_user_data(user_id, data)
            self.send_message(chat_id, f"Телефон установлен: {text}")
            keyboard = self.build_keyboard(data)
            attachments = [self.build_inline_keyboard(keyboard)]
            self.send_message(chat_id, "Пожалуйста, укажите:", attachments)
        else:
            # Default response
            self.send_message(chat_id, "Используйте команды или кнопки для взаимодействия.")

# Main loop for polling updates
def poll_updates():
    bot = MaxReservationBot()
    last_update_id = 0

    while True:
        try:
            params = {"offset": last_update_id + 1}
            response = requests.get(f"{MAX_API_URL}/updates", headers=bot.headers, params=params, timeout=30)
            response.raise_for_status()
            updates = response.json()

            for update in updates:
                last_update_id = update["update_id"]
                if "message" in update:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    user_id = message["from"]["id"]
                    text = message.get("text", "")

                    if text == "/start":
                        asyncio.run(bot.start(chat_id, user_id))
                    else:
                        # Handle text input based on state
                        asyncio.run(bot.handle_text(chat_id, user_id, text))
                elif "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback["message"]["chat"]["id"]
                    user_id = callback["from"]["id"]
                    callback_data = callback["data"]
                    bot.handle_callback(chat_id, user_id, callback_data)

        except Exception as e:
            print(f"Error polling updates: {e}")
            time.sleep(1)

if __name__ == "__main__":
    poll_updates()