from __future__ import annotations

import json
import os
import re

from datetime import date, datetime, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

from admin.comands import (
    admin_start,
    cancel_reservation,
    notify_admin_to_cancel,
    get_all_reservations,
    handle_admin_callback,
    is_admin,
    notify_admin_to_call,
    notify_new_reservation,
)
from bot.max_api import MaxAPIClient
from iiko_token.update_token import update_iiko_token
from redis_config import redis_helpers
from redis_config.redis_helpers import (
    clear_user_data,
    get_reservation_by_id,
    get_status_by_id,
    get_user_data,
    set_user_data,
    update_reservation_confirmation,
)

load_dotenv()


class ReservationBot:
    PLATFORM = "max"
    IIKO_API_URL = os.getenv("IIKO_API_URL")

    def __init__(self, app: Any = None, max_client: MaxAPIClient | None = None):
        self.application = app
        self.max_client = max_client
        self.bot_username = os.getenv("MAX_BOT_USERNAME")
        self.bot_user_id: int | None = None

    def bind_client(self, max_client: MaxAPIClient) -> None:
        self.max_client = max_client

    def bind_bot_identity(self, bot_username: str | None, bot_user_id: int | None = None) -> None:
        self.bot_username = bot_username
        self.bot_user_id = bot_user_id

    def _require_client(self) -> MaxAPIClient:
        if self.max_client is None:
            raise RuntimeError("MaxAPIClient is not configured")
        return self.max_client

    async def fetch_tables(self, token: str, terminal_group_id: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "terminalGroupIds": [terminal_group_id],
            "returnSchema": True,
            "revision": 0,
        }

        response = requests.post(
            self.IIKO_API_URL,
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()

        data = response.json()
        tables_info = []
        for section in data.get("restaurantSections", []):
            section_info = {
                "id": section["id"],
                "name": section["name"],
                "tables": [
                    {
                        "id": table["id"],
                        "number": table["number"],
                        "seatingCapacity": table["seatingCapacity"],
                        "name": table.get("name", f"Стол {table['number']}"),
                        "x": None,
                        "y": None,
                        "width": None,
                        "height": None,
                    }
                    for table in section.get("tables", [])
                    if not table.get("isDeleted", False)
                ],
            }
            if section.get("schema"):
                for table_element in section["schema"].get("tableElements", []):
                    for table in section_info["tables"]:
                        if table["id"] == table_element["tableId"]:
                            table.update(
                                {
                                    "x": table_element["x"],
                                    "y": table_element["y"],
                                    "width": table_element["width"],
                                    "height": table_element["height"],
                                }
                            )
            tables_info.append(section_info)

        return tables_info

    async def fetch_day_reservations(self, reservation_date: str):
        token = update_iiko_token(os.getenv("IIKO_KEY"))
        section_id = os.getenv("SECTION_ID")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "restaurantSectionIds": [section_id],
            "dateFrom": f"{reservation_date}T00:00:00",
            "dateTo": f"{reservation_date}T23:59:59",
        }

        response = requests.post(
            "https://api-ru.iiko.services/api/1/reserve/restaurant_sections_workload",
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("reserves", [])

    async def get_available_tables(
        self,
        reservation_date: str,
        reservation_time: str,
        guests: int,
    ) -> list[dict[str, Any]]:
        terminal_group_id = os.getenv("TERMINAL_GROUP_ID")
        token = update_iiko_token(os.getenv("IIKO_KEY"))

        tables = await self.fetch_tables(token, terminal_group_id)
        day_reservations = await self.fetch_day_reservations(reservation_date)
        requested_time = datetime.fromisoformat(f"{reservation_date}T{reservation_time}")

        reserved_table_ids: set[str] = set()
        for reservation in day_reservations:
            start = datetime.fromisoformat(reservation["estimatedStartTime"])
            duration = reservation.get("durationInMinutes", 120)
            end = start + timedelta(minutes=duration)

            if start <= requested_time < end:
                reserved_table_ids.update(reservation.get("tableIds", []))

        available_tables: list[dict[str, Any]] = []
        for section in tables:
            for table in section.get("tables", []):
                capacity = table.get("seatingCapacity") or 0
                if table["id"] in reserved_table_ids:
                    continue
                if guests and capacity and capacity < guests:
                    continue

                available_tables.append(
                    {
                        "id": table["id"],
                        "number": table["number"],
                        "name": table.get("name", f"Стол {table['number']}"),
                        "seatingCapacity": capacity,
                        "section": section["name"],
                    }
                )

        return sorted(available_tables, key=self._table_sort_key)

    async def handle_bot_started(self, update: dict[str, Any]) -> None:
        user = update.get("user") or {}
        user_id = user.get("user_id")
        if not user_id:
            return

        if is_admin(user_id):
            await admin_start(self, user_id)
            return

        await self.enter_start(user_id, user=user)

    async def handle_message_created(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        user_id = sender.get("user_id")
        body = message.get("body") or {}
        if not user_id:
            return

        print(message)
        await self._remember_dialog_context(user_id, sender, recipient)
        text = (body.get("text") or "").strip()
        if text.startswith("BOOKING_DATA:"):
            await self._handle_web_app_booking_message(
                user_id=user_id,
                sender=sender,
                recipient=recipient,
                text=text,
            )
            return

        lowered = text.lower()
        if is_admin(user_id):
            if lowered in {"", "/start", "start", "привет", "меню", "/menu"}:
                await admin_start(self, user_id)
                return

            await admin_start(self, user_id)
            return

        if lowered in {"/start", "start", "привет", "меню", "/menu"}:
            await self.enter_start(user_id, user=sender)
            return

        data = await get_user_data(user_id)
        step = data.get("step")

        if not step:
            await self.enter_start(user_id, user=sender)
            return

        if step == "name":
            await self._handle_name_input(user_id, text)
            return
        if step == "date":
            await self._handle_date_input(user_id, text)
            return
        if step == "time":
            await self._handle_time_input(user_id, text)
            return
        if step == "guests":
            await self._handle_guests_input(user_id, text)
            return

        await self.enter_start(user_id, user=sender)

    async def handle_callback(self, update: dict[str, Any]) -> None:
        callback = update.get("callback") or {}
        payload = callback.get("payload") or ""
        callback_id = callback.get("callback_id")
        user = callback.get("user") or {}
        user_id = user.get("user_id")

        if not callback_id or not user_id:
            return

        if is_admin(user_id):
            handled = await handle_admin_callback(self, update)
            if handled:
                return
            if payload == "back_to_start":
                await admin_start(self, user_id, callback_id=callback_id)
                return

        if payload == "back_to_start":
            await self.enter_start(user_id, user=user, callback_id=callback_id)
            return

        if payload == "my_reservations":
            await self.reservations(user_id, callback_id)
            return

        if payload.startswith("show_reservations:"):
            _, status = payload.split(":", 1)
            await self.show_user_reservations(user_id, status, callback_id)
            return

        if payload.startswith("detail_reservation:"):
            _, reservation_id = payload.split(":", 1)
            await self.view_detail_reservation(user_id, reservation_id, callback_id)
            return

        if payload.startswith("cancel:"):
            _, reservation_id = payload.split(":", 1)
            await self.ask_cancel_confirmation(user_id, reservation_id, callback_id)
            return

        if payload.startswith("confirm_cancel:"):
            _, reservation_id = payload.split(":", 1)
            await self.confirm_cancel_reservation(user_id, reservation_id, callback_id)
            return

        if payload.startswith("deny_cancel:"):
            _, reservation_id = payload.split(":", 1)
            await self.deny_cancel_reservation(user_id, reservation_id, callback_id)
            return

        if payload.startswith("tables_page:"):
            _, raw_page = payload.split(":", 1)
            await self.show_table_selection(user_id, callback_id, int(raw_page))
            return

        if payload.startswith("select_table:"):
            _, table_id = payload.split(":", 1)
            await self.select_table(user_id, table_id, callback_id)
            return

        if payload == "change_time":
            await self.ask_time(user_id, callback_id=callback_id)
            return

        if payload == "confirm_reservation":
            await self.confirm_reservation(user_id, callback_id)
            return

        if payload.startswith("confirm_yes:"):
            _, reservation_id = payload.split(":", 1)
            await self.confirm_visit_yes(reservation_id, callback_id)
            return

        if payload.startswith("confirm_no:"):
            _, reservation_id = payload.split(":", 1)
            await self.confirm_visit_no(reservation_id, callback_id)
            return

        await self._answer_notification(callback_id, "Действие не распознано")

    async def enter_start(
        self,
        user_id: int,
        user: dict[str, Any] | None = None,
        callback_id: str | None = None,
    ) -> None:
        await self.show_start_menu(user_id, user=user, callback_id=callback_id)

    async def show_start_menu(
        self,
        user_id: int,
        user: dict[str, Any] | None = None,
        callback_id: str | None = None,
    ) -> None:
        await self._prepare_booking_context(user_id, user)
        booking_button = (
            self._web_app_button("📅 Забронировать стол", self.bot_username)
            if self.bot_username
            else self._callback_button("📅 Забронировать стол", "create_reservation")
        )
        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text="Добро пожаловать в Таврику. Что бы вы хотели?",
            buttons=[
                [booking_button],
                [self._callback_button("📋 Мои брони", "my_reservations")],
            ],
        )

    async def start_reservation_flow(
        self,
        user_id: int,
        user: dict[str, Any],
        other_people: bool,
        callback_id: str,
    ) -> None:
        current_data = await get_user_data(user_id)
        data = {
            "platform": self.PLATFORM,
            "for_another_person": other_people,
        }
        for key in ("chat_id", "profile_name"):
            if key in current_data:
                data[key] = current_data[key]

        if not other_people:
            data["name"] = self._extract_user_name(user)
            if current_data.get("phone"):
                data["phone"] = current_data["phone"]

        await set_user_data(user_id, data)

        if other_people:
            await self._set_step(
                user_id,
                "name",
                "Введите имя гостя.",
                callback_id=callback_id,
            )
            return

        await self._set_step(
            user_id,
            "date",
            "Введите дату брони в формате `ДД.ММ.ГГГГ` или `YYYY-MM-DD`.",
            callback_id=callback_id,
        )

    async def ask_time(self, user_id: int, callback_id: str | None = None) -> None:
        await self._set_step(
            user_id,
            "time",
            "Введите время брони в формате `HH:MM`, например `19:30`.",
            callback_id=callback_id,
        )

    async def confirm_reservation(self, user_id: int, callback_id: str) -> None:
        data = await get_user_data(user_id)
        required_fields = ("name", "phone", "date", "time", "guests", "table", "tableId")
        if any(field not in data for field in required_fields):
            await self._answer_notification(callback_id, "Не все данные для брони заполнены")
            return

        reservation_data = {
            "user_id": user_id,
            "platform": self.PLATFORM,
            "eventType": "max_bot",
            "name": data["name"],
            "phone": data["phone"],
            "guests": data["guests"],
            "table": data["table"],
            "tableId": data["tableId"],
            "date": data["date"],
            "time": data["time"],
        }
        await redis_helpers.save_reservation(reservation_data)
        await clear_user_data(user_id)

        text = (
            "Заявка создана.\n\n"
            f"Имя: {reservation_data['name']}\n"
            f"Телефон: {reservation_data['phone']}\n"
            f"Гостей: {reservation_data['guests']}\n"
            f"Дата: {reservation_data['date']}\n"
            f"Время: {reservation_data['time']}\n"
            f"Стол: {reservation_data['table']}\n\n"
            "Дождитесь ответа администратора."
        )

        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text=text,
            buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
        )

    async def _handle_web_app_booking_message(
        self,
        *,
        user_id: int,
        sender: dict[str, Any],
        recipient: dict[str, Any],
        text: str,
    ) -> None:
        raw_payload = text.removeprefix("BOOKING_DATA:")
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            await self._send_message(
                user_id,
                "Не удалось прочитать данные бронирования из WebApp.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        payload_user_id = self._safe_int(payload.get("userId"))
        if payload_user_id is not None and payload_user_id != user_id:
            await self._send_message(
                user_id,
                "Не удалось подтвердить пользователя для бронирования.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        guest_name = self._normalize_name(payload.get("guestName")) or self._extract_user_name(sender)
        phone = self._normalize_phone(str(payload.get("guestPhone", "")).strip())
        reservation_date = self._parse_date(str(payload.get("date", "")).strip())
        reservation_time = self._parse_time(str(payload.get("time", "")).strip())
        guests = self._safe_int(payload.get("guestCount"))
        table_number = payload.get("tableNumber")

        if not guest_name:
            await self._send_message(
                user_id,
                "Не удалось определить имя гостя.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        if not phone:
            await self._send_message(
                user_id,
                "Некорректный номер телефона в данных WebApp.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        if reservation_date is None or reservation_time is None:
            await self._send_message(
                user_id,
                "Некорректная дата или время в данных WebApp.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        if guests is None or not 1 <= guests <= 20:
            await self._send_message(
                user_id,
                "Количество гостей должно быть от 1 до 20.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        if table_number in (None, ""):
            await self._send_message(
                user_id,
                "Не удалось определить выбранный стол.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        date_value = reservation_date.isoformat()
        time_value = reservation_time.strftime("%H:%M")
        available_tables = await self.get_available_tables(
            reservation_date=date_value,
            reservation_time=time_value,
            guests=guests,
        )
        selected_table = next(
            (table for table in available_tables if str(table.get("number")) == str(table_number)),
            None,
        )
        if selected_table is None:
            await self._send_message(
                user_id,
                "Выбранный стол уже недоступен. Попробуйте выбрать другой стол в приложении.",
                buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
            )
            return

        chat_id = self._safe_int(payload.get("chatId")) or recipient.get("chat_id")
        preserved_data: dict[str, Any] = {
            "profile_name": guest_name,
            "phone": phone,
        }
        if chat_id is not None:
            preserved_data["chat_id"] = chat_id
        await set_user_data(user_id, preserved_data)

        reservation_data = {
            "user_id": user_id,
            "platform": self.PLATFORM,
            "eventType": payload.get("source") or "max_web_app",
            "name": guest_name,
            "phone": phone,
            "guests": guests,
            "table": selected_table["number"],
            "tableId": selected_table["id"],
            "date": date_value,
            "time": time_value,
            "occasion": payload.get("occasion") or "-",
        }
        await redis_helpers.save_reservation(reservation_data)

        confirmation_text = (
            "Заявка создана.\n\n"
            f"Имя: {reservation_data['name']}\n"
            f"Телефон: {reservation_data['phone']}\n"
            f"Гостей: {reservation_data['guests']}\n"
            f"Дата: {reservation_data['date']}\n"
            f"Время: {reservation_data['time']}\n"
            f"Стол: {reservation_data['table']}\n\n"
            "Дождитесь ответа администратора."
        )
        await self._send_message(
            user_id,
            confirmation_text,
            buttons=[[self._callback_button("🏠 В меню", "back_to_start")]],
        )

    async def reservations(self, user_id: int, callback_id: str) -> None:
        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text="Выберите тип броней:",
            buttons=[
                [self._callback_button("✅ Подтверждённые", "show_reservations:CONFIRMED")],
                [self._callback_button("⏳ В ожидании", "show_reservations:PENDING")],
                [self._callback_button("⬅️ Назад", "back_to_start")],
            ],
        )

    async def show_user_reservations(
        self,
        user_id: int,
        status: str,
        callback_id: str,
    ) -> None:
        reservations = await get_all_reservations()
        user_reservations = [
            reservation
            for reservation in reservations
            if reservation["user_id"] == user_id
            # and reservation.get("platform", "telegram") == self.PLATFORM
            and reservation["status"] == status
        ]

        if not user_reservations:
            await self._respond(
                user_id=user_id,
                callback_id=callback_id,
                text="У вас нет броней в этом разделе.",
                buttons=[
                    [self._callback_button("⬅️ Назад", "my_reservations")],
                    [self._callback_button("🏠 В меню", "back_to_start")],
                ],
            )
            return

        buttons = [
            [
                self._callback_button(
                    f"📅 {reservation['date']} {reservation['time']} · стол {reservation['table']}",
                    f"detail_reservation:{reservation['id']}",
                )
            ]
            for reservation in user_reservations
        ]
        buttons.append([self._callback_button("⬅️ Назад", "my_reservations")])

        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text="Ваши брони:",
            buttons=buttons,
        )

    async def view_detail_reservation(
        self,
        user_id: int,
        reservation_id: str,
        callback_id: str,
    ) -> None:
        reservation = await get_reservation_by_id(reservation_id)
        if not reservation or reservation.get("platform", "telegram") != self.PLATFORM:
            await self._answer_notification(callback_id, "Бронь не найдена")
            return

        text = (
            f"Имя: {reservation['name']}\n"
            f"Телефон: {reservation['phone']}\n"
            f"Гостей: {reservation['guests']}\n"
            f"Дата: {reservation['date']} {reservation['time']}\n"
            f"Стол: {reservation['table']}\n"
            f"Статус: {reservation['status']}"
        )

        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text=text,
            buttons=[
                [self._callback_button("❌ Отменить бронь", f"cancel:{reservation_id}", intent="negative")],
                [self._callback_button("⬅️ Назад", "my_reservations")],
            ],
        )

    async def ask_cancel_confirmation(
        self,
        user_id: int,
        reservation_id: str,
        callback_id: str,
    ) -> None:
        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text="Точно удалить бронь?",
            buttons=[
                [
                    self._callback_button("🗑️ Да, удалить", f"confirm_cancel:{reservation_id}", intent="negative"),
                    self._callback_button("↩️ Нет", f"deny_cancel:{reservation_id}"),
                ]
            ],
        )

    async def confirm_cancel_reservation(
        self,
        user_id: int,
        reservation_id: str,
        callback_id: str,
    ) -> None:
        reservation = await get_reservation_by_id(reservation_id)
        status = await get_status_by_id(reservation_id)
        if status == "CONFIRMED":
            await cancel_reservation(reservation_id)
            await notify_admin_to_cancel(None, reservation)
        await redis_helpers.delete_reservation_by_id(reservation_id)

        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text="Бронь успешно удалена.",
            buttons=[[self._callback_button("📋 Мои брони", "my_reservations")]],
        )

    async def deny_cancel_reservation(
        self,
        user_id: int,
        reservation_id: str,
        callback_id: str,
    ) -> None:
        reservation = await get_reservation_by_id(reservation_id)
        if not reservation:
            await self._answer_notification(callback_id, "Бронь не найдена")
            return

        await self.view_detail_reservation(user_id, reservation_id, callback_id)

    async def confirm_visit_yes(self, reservation_id: str, callback_id: str) -> None:
        await update_reservation_confirmation(reservation_id, "CONFIRMED")
        client = self._require_client()
        await client.answer_callback(
            callback_id,
            text="Хорошо, ждём вас.",
        )

    async def confirm_visit_no(self, reservation_id: str, callback_id: str) -> None:
        reservation = await get_reservation_by_id(reservation_id)
        if not reservation:
            await self._answer_notification(callback_id, "Бронь не найдена")
            return

        await update_reservation_confirmation(reservation_id, "DECLINED")
        reservation["confirmation_status"] = "DECLINED"

        if reservation.get("status") == "CONFIRMED":
            await cancel_reservation(reservation_id)

        await redis_helpers.delete_reservation_by_id(reservation_id)
        await notify_admin_to_call(None, reservation)

        client = self._require_client()
        await client.answer_callback(
            callback_id,
            text="Поняли, спасибо, что предупредили.",
        )

    async def new_reservation_notification(self, reservation_json: str):
        await notify_new_reservation(self, reservation_json)


    async def _set_step(
        self,
        user_id: int,
        step: str,
        text: str,
        callback_id: str | None = None,
        buttons: list[list[dict[str, Any]]] | None = None,
        include_menu_button: bool = True,
    ) -> None:
        data = await get_user_data(user_id)
        data["step"] = step
        await set_user_data(user_id, data)

        action_buttons = [row[:] for row in buttons] if buttons else []
        if include_menu_button:
            action_buttons.append([self._callback_button("🏠 В меню", "back_to_start")])

        await self._respond(
            user_id=user_id,
            callback_id=callback_id,
            text=text,
            buttons=action_buttons,
            format="markdown",
        )

    async def _send_message(
        self,
        user_id: int,
        text: str,
        buttons: list[list[dict[str, Any]]] | None = None,
        format: str | None = "markdown",
    ) -> dict[str, Any]:
        client = self._require_client()
        target = await self._resolve_target(user_id)
        return await client.send_message(
            user_id=target.get("user_id"),
            chat_id=target.get("chat_id"),
            text=text,
            attachments=self._build_keyboard(buttons),
            format=format,
        )

    async def _respond(
        self,
        *,
        user_id: int,
        callback_id: str | None,
        text: str,
        buttons: list[list[dict[str, Any]]] | None = None,
        format: str | None = None,
    ) -> None:
        client = self._require_client()
        response_attachments = self._build_keyboard(buttons)

        if callback_id:
            await client.answer_callback(
                callback_id,
                text=text,
                attachments=response_attachments,
                format=format,
            )
            return

        target = await self._resolve_target(user_id)
        await client.send_message(
            user_id=target.get("user_id"),
            chat_id=target.get("chat_id"),
            text=text,
            attachments=response_attachments,
            format=format,
        )

    async def _answer_notification(self, callback_id: str, notification: str) -> None:
        client = self._require_client()
        await client.answer_callback(callback_id, notification=notification)

    async def _prepare_booking_context(
        self,
        user_id: int,
        user: dict[str, Any] | None = None,
    ) -> None:
        current_data = await get_user_data(user_id)

        profile_name = self._extract_user_name(user) if user else current_data.get("profile_name")
        phone = current_data.get("phone", "")
        chat_id = current_data.get("chat_id")

        preserved_data: dict[str, Any] = {}
        if phone:
            preserved_data["phone"] = phone
        if profile_name:
            preserved_data["profile_name"] = profile_name
        if chat_id is not None:
            preserved_data["chat_id"] = chat_id

        if preserved_data:
            await set_user_data(user_id, preserved_data)
        else:
            await clear_user_data(user_id)

    async def _resolve_target(self, user_id: int) -> dict[str, int]:
        data = await get_user_data(user_id)
        chat_id = data.get("chat_id")
        if chat_id is not None:
            return {"chat_id": int(chat_id)}
        return {"user_id": user_id}

    async def _remember_dialog_context(
        self,
        user_id: int,
        user: dict[str, Any],
        recipient: dict[str, Any],
    ) -> None:
        data = await get_user_data(user_id)

        profile_name = self._extract_user_name(user)
        if profile_name:
            data["profile_name"] = profile_name

        chat_id = recipient.get("chat_id")
        if chat_id is not None:
            data["chat_id"] = chat_id

        await set_user_data(user_id, data)

    def _build_keyboard(
        self,
        buttons: list[list[dict[str, Any]]] | None,
    ) -> list[dict[str, Any]]:
        if not buttons:
            return []
        return [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": buttons,
                },
            }
        ]

    @staticmethod
    def _callback_button(text: str, payload: str, intent: str | None = None) -> dict[str, Any]:
        button = {
            "type": "callback",
            "text": text,
            "payload": payload,
        }
        if intent:
            button["intent"] = intent
        return button


    @staticmethod
    def _web_app_button(
        text: str,
        web_app: str,
        contact_id: int | None = None,
    ) -> dict[str, Any]:
        button = {
            "type": "open_app",
            "text": text,
            "web_app": web_app,
        }
        return button
    
    @staticmethod
    def _link_button(text: str, url: str) -> dict[str, Any]:
        return {
            "type": "link",
            "text": text,
            "url": url,
        }

    @staticmethod
    def _extract_user_name(user: dict[str, Any]) -> str:
        return (
            user.get("first_name")
            or user.get("name")
            or user.get("username")
            or "Гость"
        )

    @staticmethod
    def _normalize_name(raw_name: Any) -> str | None:
        if raw_name is None:
            return None

        normalized = " ".join(str(raw_name).split())
        if len(normalized) < 2:
            return None
        return normalized

    @staticmethod
    def _normalize_phone(raw_phone: str) -> str | None:
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) == 11 and digits.startswith("8"):
            digits = f"7{digits[1:]}"

        if not 10 <= len(digits) <= 15:
            return None

        return f"+{digits}"

    @staticmethod
    def _parse_date(raw_date: str) -> date | None:
        cleaned = raw_date.strip()
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue

            if parsed < date.today():
                return None
            return parsed

        return None

    @staticmethod
    def _parse_time(raw_time: str) -> datetime.time | None:
        cleaned = raw_time.strip().replace(".", ":")
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(cleaned, fmt).time()
            except ValueError:
                continue
        return None

    @staticmethod
    def _table_sort_key(table: dict[str, Any]) -> tuple[int, str]:
        number = str(table.get("number", ""))
        digits = re.sub(r"\D", "", number)
        if digits:
            return (0, digits.zfill(6))
        return (1, number)

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
