from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from telegram import Bot

from bot.max_api import MaxAPIClient
from bot.reminder_mes import schedule_reservation_reminders
from iiko_token.update_token import update_iiko_token
from redis_config import redis_client as redis
from redis_config.redis_helpers import (
    clear_reservation_admin_notifications,
    delete_reservation_by_id,
    get_iikoId_by_id,
    get_reservation_by_id,
    get_user_data,
    update_reservation_admin_notification,
    update_reservation_status,
)

load_dotenv()

redis = redis.redis_client

PAGE_SIZE = 5
ADMIN_TRANSPORT = os.getenv("ADMIN_TRANSPORT", "max").lower()
ADMIN_NOTIFICATION_SOURCE = "notification"


def is_admin(user_id: int) -> bool:
    admin_ids = os.getenv("ADMIN_IDS", "")
    return user_id in [int(item) for item in admin_ids.split(",") if item]


def is_admin_payload(payload: str) -> bool:
    return payload == "admin:menu" or payload.startswith(
        (
            "admin:view_reservations",
            "admin:page:",
            "admin:reservation:",
            "admin:approve:",
            "admin:reject:",
        )
    )


def _parse_reservation_action_payload(payload: str) -> tuple[str, str | None]:
    parts = payload.split(":")
    reservation_id = parts[2]
    source = parts[3] if len(parts) > 3 else None
    return reservation_id, source


def _reservation_payload(reservation_id: str, source: str | None = None) -> str:
    payload = f"admin:reservation:{reservation_id}"
    if source:
        return f"{payload}:{source}"
    return payload


def _decision_payload(action: str, reservation_id: str, source: str | None = None) -> str:
    payload = f"admin:{action}:{reservation_id}"
    if source:
        return f"{payload}:{source}"
    return payload


async def get_all_reservations() -> list[dict[str, Any]]:
    ids = await redis.lrange("reservation:requests", 0, -1)

    reservations: list[dict[str, Any]] = []
    for reservation_id in ids:
        data = await redis.get(f"reservation:request:{reservation_id}")
        if data:
            reservations.append(json.loads(data))

    reservations.sort(key=lambda item: f"{item.get('date', '')}T{item.get('time', '')}")
    return reservations


async def admin_start(bot: Any, user_id: int, callback_id: str | None = None) -> None:
    await _respond(
        bot,
        user_id=user_id,
        callback_id=callback_id,
        text="Панель администратора. Выберите действие.",
        buttons=[
            [_callback_button("Посмотреть заявки", "admin:view_reservations", intent="positive")],
        ],
    )


async def handle_admin_callback(bot: Any, update: dict[str, Any]) -> bool:
    callback = update.get("callback") or {}
    payload = callback.get("payload") or ""
    callback_id = callback.get("callback_id")
    user = callback.get("user") or {}
    user_id = user.get("user_id")

    if not user_id or not callback_id or not is_admin_payload(payload):
        return False

    if payload == "admin:menu":
        await admin_start(bot, user_id, callback_id=callback_id)
        return True

    if payload == "admin:view_reservations":
        await show_reservations(bot, user_id, callback_id=callback_id, page=0)
        return True

    if payload.startswith("admin:page:"):
        page = int(payload.rsplit(":", 1)[1])
        await show_reservations(bot, user_id, callback_id=callback_id, page=page)
        return True

    if payload.startswith("admin:reservation:"):
        reservation_id, source = _parse_reservation_action_payload(payload)
        await view_reservation(
            bot,
            user_id,
            reservation_id,
            callback_id=callback_id,
            source=source,
        )
        return True

    if payload.startswith("admin:approve:"):
        reservation_id, source = _parse_reservation_action_payload(payload)
        await handle_reservation_decision(
            bot,
            user_id,
            reservation_id,
            approved=True,
            callback_id=callback_id,
            source=source,
        )
        return True

    if payload.startswith("admin:reject:"):
        reservation_id, source = _parse_reservation_action_payload(payload)
        await handle_reservation_decision(
            bot,
            user_id,
            reservation_id,
            approved=False,
            callback_id=callback_id,
            source=source,
        )
        return True

    return False


async def show_reservations(
    bot: Any,
    user_id: int,
    callback_id: str | None = None,
    page: int = 0,
) -> None:
    reservations = _pending_reservations(await get_all_reservations())

    if not reservations:
        await _respond(
            bot,
            user_id=user_id,
            callback_id=callback_id,
            text="Сейчас активных заявок нет.",
            buttons=[[_callback_button("В меню", "admin:menu")]],
        )
        return

    total_pages = max(1, (len(reservations) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start_index = page * PAGE_SIZE
    page_items = reservations[start_index : start_index + PAGE_SIZE]

    buttons = []
    for reservation in page_items:
        label = (
            f"{reservation['date']} {reservation['time']} · "
            f"{reservation['name']} · стол {reservation['table']}"
        )
        buttons.append(
            [_callback_button(label, f"admin:reservation:{reservation['id']}")]
        )

    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(_callback_button("Назад", f"admin:page:{page - 1}"))
    if page < total_pages - 1:
        pagination_buttons.append(_callback_button("Дальше", f"admin:page:{page + 1}"))
    if pagination_buttons:
        buttons.append(pagination_buttons)

    buttons.append([_callback_button("В меню", "admin:menu")])

    await _respond(
        bot,
        user_id=user_id,
        callback_id=callback_id,
        text=f"Заявки: страница {page + 1} из {total_pages}.",
        buttons=buttons,
    )


async def view_reservation(
    bot: Any,
    user_id: int,
    reservation_id: str,
    callback_id: str | None = None,
    source: str | None = None,
) -> None:
    reservations = _pending_reservations(await get_all_reservations())
    index = next((i for i, item in enumerate(reservations) if item["id"] == reservation_id), None)

    if index is None:
        if source == ADMIN_NOTIFICATION_SOURCE and callback_id is not None:
            await _respond(
                bot,
                user_id=user_id,
                callback_id=callback_id,
                text="Заявка уже обработана.",
            )
            return

        await _respond(
            bot,
            user_id=user_id,
            callback_id=callback_id,
            text="Заявка не найдена или уже обработана.",
            buttons=[[_callback_button("К списку", "admin:view_reservations")]],
        )
        return

    reservation = reservations[index]
    total = len(reservations)

    nav_buttons = []
    if index > 0:
        nav_buttons.append(
            _callback_button(
                "⬅️",
                _reservation_payload(reservations[index - 1]["id"], source),
            )
        )
    nav_buttons.append(_callback_button("К списку", "admin:view_reservations"))
    if index < total - 1:
        nav_buttons.append(
            _callback_button(
                "➡️",
                _reservation_payload(reservations[index + 1]["id"], source),
            )
        )

    text = (
        f"Заявка {index + 1} из {total}\n\n"
        f"Имя: {reservation['name']}\n"
        f"Телефон: {reservation['phone']}\n"
        f"Гостей: {reservation['guests']}\n"
        f"Дата: {reservation['date']} {reservation['time']}\n"
        f"Стол: {reservation['table']}\n"
        f"Платформа: {reservation.get('platform', 'telegram')}\n"
        f"Статус: {reservation['status']}"
    )

    await _respond(
        bot,
        user_id=user_id,
        callback_id=callback_id,
        text=text,
        buttons=[
            nav_buttons,
            [
                _callback_button(
                    "Принять",
                    _decision_payload("approve", reservation_id, source),
                    intent="positive",
                ),
                _callback_button(
                    "Отклонить",
                    _decision_payload("reject", reservation_id, source),
                    intent="negative",
                ),
            ],
            [_callback_button("В меню", "admin:menu")],
        ],
    )


def format_phone(phone: str) -> str:
    digits = "".join(filter(str.isdigit, phone))
    if digits.startswith("8"):
        digits = f"7{digits[1:]}"
    return f"+{digits}"


async def create_reserve(reservation_data: dict[str, Any]) -> dict[str, Any]:
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
            "type": "one-time",
        },
        "phone": format_phone(reservation_data["phone"]),
        "guestsCount": reservation_data.get("guests", 2),
        "comment": "MAX bot reservation",
        "durationInMinutes": 120,
        "shouldRemind": True,
        "tableIds": [reservation_data["table_id"]],
        "estimatedStartTime": iso_date,
        "eventType": reservation_data.get("eventType", "max_bot"),
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(os.getenv("IIKO_CREATE_URL"), headers=headers, json=body)

    if response.status_code != 200:
        return {"status": "error", "error": response.text}

    return {"status": "created", "reserve_id": reserve_id, "iiko": response.json()}


async def cancel_reservation(reservation_id: str) -> dict[str, Any]:
    iiko_id = await get_iikoId_by_id(reservation_id)
    if not iiko_id:
        raise ValueError("iiko reserveId not found for this reservation")

    token = update_iiko_token(os.getenv("IIKO_KEY"))
    body = {
        "organizationId": os.getenv("ORGANIZATION_ID"),
        "reserveId": iiko_id,
        "cancelReason": "ClientRefused",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            os.getenv("IIKO_CANCEL_URL"),
            json=body,
            headers=headers,
        )

    if response.status_code == 400:
        return {"success": False, "reason": response.text}

    response.raise_for_status()
    return {"success": True, "data": response.json()}


async def handle_reservation_decision(
    bot: Any,
    admin_user_id: int,
    reservation_id: str,
    approved: bool,
    callback_id: str | None = None,
    context: Any | None = None,
    source: str | None = None,
) -> None:
    reservation = await get_reservation_by_id(reservation_id)

    if not reservation:
        if source == ADMIN_NOTIFICATION_SOURCE and callback_id is not None:
            await _respond(
                bot,
                user_id=admin_user_id,
                callback_id=callback_id,
                text="Заявка уже обработана.",
            )
            return

        await _respond(
            bot,
            user_id=admin_user_id,
            callback_id=callback_id,
            text="Заявка не найдена.",
            buttons=[[_callback_button("К списку", "admin:view_reservations")]],
        )
        return

    if approved:
        user_text = (
            "Ваша заявка подтверждена.\n\n"
            f"Дата: {reservation['date']} {reservation['time']}\n"
            f"Стол: {reservation['table']}\n"
            f"Гостей: {reservation['guests']}"
        )
        reservation_data = {
            "id": reservation["id"],
            "name": reservation["name"],
            "phone": reservation["phone"],
            "table_id": reservation["tableId"],
            "table": reservation["table"],
            "guests": reservation["guests"],
            "date": reservation["date"],
            "time": reservation["time"],
            "eventType": reservation.get("eventType", "max_bot"),
        }
        reservation_result = await create_reserve(reservation_data)

        if reservation_result["status"] != "created":
            await _respond(
                bot,
                user_id=admin_user_id,
                callback_id=callback_id,
                text=f"Ошибка при создании брони в iiko.\n{reservation_result['error']}",
                buttons=[
                    [
                        _callback_button(
                            "Повторить",
                            _decision_payload("approve", reservation_id, source),
                            intent="positive",
                        )
                    ],
                    [_callback_button("К заявке", _reservation_payload(reservation_id, source))],
                ],
            )
            return

        iiko_id = reservation_result["iiko"]["reserveInfo"]["id"]
        await update_reservation_status(reservation_id, "CONFIRMED", iiko_id)
        reservation["status"] = "CONFIRMED"
        schedule_reservation_reminders(context, reservation)
        admin_text = "Заявка подтверждена."
    else:
        user_text = (
            "К сожалению, ваша заявка отклонена.\n"
            f"Дата: {reservation['date']} {reservation['time']}\n"
            f"Стол: {reservation['table']}\n"
            f"Гостей: {reservation['guests']}\n\n"
            "Попробуйте выбрать другое время или другой стол."
        )
        await delete_reservation_by_id(reservation_id)
        admin_text = "Заявка отклонена."

    await _send_user_notification(reservation, user_text, context=context)
    deleted_notification_admin_ids = await _delete_admin_notification_messages(reservation)

    if source == ADMIN_NOTIFICATION_SOURCE and callback_id is not None:
        if str(admin_user_id) in deleted_notification_admin_ids:
            await _answer_admin_callback_notification(bot, callback_id, admin_text)
        else:
            await _respond(
                bot,
                user_id=admin_user_id,
                callback_id=callback_id,
                text=admin_text,
            )
        return

    await show_reservations(
        bot,
        admin_user_id,
        callback_id=callback_id,
        page=0,
    )
    if callback_id is None:
        await _send_to_admin(admin_user_id, admin_text)


async def notify_admin_to_call(context: Any, reservation: dict[str, Any]) -> None:
    admin_ids = _admin_ids()

    text = (
        "Гость не подтвердил бронь.\n\n"
        f"Имя: {reservation['name']}\n"
        f"Телефон: {reservation['phone']}\n"
        f"Дата: {reservation['date']} {reservation['time']}\n"
        f"Стол: {reservation['table']}\n"
        f"Статус подтверждения: {reservation['confirmation_status']}"
    )

    if ADMIN_TRANSPORT == "telegram":
        await _send_to_telegram_admins(admin_ids, text)
        return

    buttons = []
    if reservation.get("status") != "CONFIRMED":
        buttons.append([_callback_button("Открыть заявку", f"admin:reservation:{reservation['id']}")])
    else:
        buttons.append([_callback_button("К списку", "admin:view_reservations")])

    for admin_id in admin_ids:
        await _send_to_admin(admin_id, text, buttons=buttons)


async def notify_new_reservation(bot: Any, reservation_json: str | bytes) -> None:
    if isinstance(reservation_json, bytes):
        reservation_json = reservation_json.decode("utf-8")

    reservation = json.loads(reservation_json)
    text = (
        "Новая заявка.\n\n"
        f"Имя: {reservation['name']}\n"
        f"Телефон: {reservation['phone']}\n"
        f"Дата: {reservation['date']} {reservation['time']}\n"
        f"Стол: {reservation['table']}\n"
        f"Гостей: {reservation['guests']}"
    )

    buttons = [
        [
            _callback_button(
                "Открыть заявку",
                _reservation_payload(reservation["id"], ADMIN_NOTIFICATION_SOURCE),
                intent="positive",
            )
        ],
        [_callback_button("К списку", "admin:view_reservations")],
    ]

    for admin_id in _admin_ids():
        response = await _send_to_admin(admin_id, text, buttons=buttons, bot=bot)
        message_id = _extract_message_id(response)
        if message_id is not None:
            await update_reservation_admin_notification(reservation["id"], admin_id, message_id)


def _admin_ids() -> list[int]:
    return [int(item) for item in os.getenv("ADMIN_IDS", "").split(",") if item]


def _pending_reservations(reservations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [reservation for reservation in reservations if reservation.get("status") != "CONFIRMED"]


def _callback_button(text: str, payload: str, intent: str | None = None) -> dict[str, Any]:
    button = {
        "type": "callback",
        "text": text,
        "payload": payload,
    }
    if intent:
        button["intent"] = intent
    return button


def _build_keyboard(buttons: list[list[dict[str, Any]]] | None) -> list[dict[str, Any]]:
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


async def _respond(
    bot: Any,
    *,
    user_id: int,
    text: str,
    buttons: list[list[dict[str, Any]]] | None = None,
    callback_id: str | None = None,
) -> None:
    if bot is not None and hasattr(bot, "_respond"):
        await bot._respond(
            user_id=user_id,
            callback_id=callback_id,
            text=text,
            buttons=buttons,
        )
        return

    if callback_id:
        client = MaxAPIClient()
        try:
            await client.answer_callback(
                callback_id,
                text=text,
                attachments=_build_keyboard(buttons),
            )
        finally:
            await client.close()
        return

    await _send_to_admin(user_id, text, buttons=buttons, bot=bot)


async def _send_user_notification(
    reservation: dict[str, Any],
    text: str,
    context: Any | None = None,
) -> None:
    if reservation.get("platform", "telegram") == "max":
        await _send_max_message(reservation["user_id"], text)
        return

    if context is not None:
        await context.bot.send_message(chat_id=reservation["user_id"], text=text)
        return

    telegram_bot = Bot(os.getenv("TOKEN"))
    await telegram_bot.send_message(chat_id=reservation["user_id"], text=text)


async def _send_to_admin(
    admin_id: int,
    text: str,
    buttons: list[list[dict[str, Any]]] | None = None,
    bot: Any | None = None,
) -> Any:
    if ADMIN_TRANSPORT == "telegram":
        telegram_bot = Bot(os.getenv("TOKEN"))
        return await telegram_bot.send_message(chat_id=admin_id, text=text)

    if bot is not None and hasattr(bot, "_send_message"):
        return await bot._send_message(admin_id, text, buttons=buttons)

    return await _send_max_message(admin_id, text, buttons=buttons)


async def _send_to_telegram_admins(admin_ids: list[int], text: str) -> None:
    telegram_bot = Bot(os.getenv("TOKEN"))
    for admin_id in admin_ids:
        await telegram_bot.send_message(chat_id=admin_id, text=text)


async def _send_max_message(
    user_id: int,
    text: str,
    buttons: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    client = MaxAPIClient()
    try:
        target = await _resolve_max_target(user_id)
        return await client.send_message(
            user_id=target.get("user_id"),
            chat_id=target.get("chat_id"),
            text=text,
            attachments=_build_keyboard(buttons),
        )
    finally:
        await client.close()


def _extract_message_id(response: Any) -> str | int | None:
    if response is None:
        return None

    if hasattr(response, "message_id"):
        return response.message_id

    if not isinstance(response, dict):
        return None

    return ((response.get("message") or {}).get("body") or {}).get("mid")


async def _delete_admin_notification_messages(reservation: dict[str, Any]) -> set[str]:
    notifications = reservation.get("admin_notifications") or {}
    deleted_admin_ids: set[str] = set()

    for raw_admin_id, message_id in notifications.items():
        try:
            admin_id = int(raw_admin_id)
        except (TypeError, ValueError):
            continue

        try:
            await _delete_admin_notification_message(admin_id, message_id)
        except Exception as exc:
            print(
                "Не удалось удалить админское уведомление "
                f"по заявке {reservation.get('id')} для admin_id={admin_id}: {exc}"
            )
        else:
            deleted_admin_ids.add(str(admin_id))

    reservation["admin_notifications"] = {}
    await clear_reservation_admin_notifications(reservation["id"])
    return deleted_admin_ids


async def _delete_admin_notification_message(admin_id: int, message_id: str | int) -> None:
    if ADMIN_TRANSPORT == "telegram":
        telegram_bot = Bot(os.getenv("TOKEN"))
        await telegram_bot.delete_message(chat_id=admin_id, message_id=int(message_id))
        return

    client = MaxAPIClient()
    try:
        await client.delete_message(message_id)
    finally:
        await client.close()


async def _answer_admin_callback_notification(
    bot: Any,
    callback_id: str,
    notification: str,
) -> None:
    if bot is not None and hasattr(bot, "_answer_notification"):
        await bot._answer_notification(callback_id, notification)
        return

    client = MaxAPIClient()
    try:
        await client.answer_callback(callback_id, notification=notification)
    finally:
        await client.close()


async def _resolve_max_target(user_id: int) -> dict[str, int]:
    data = await get_user_data(user_id)
    chat_id = data.get("chat_id")
    if chat_id is not None:
        return {"chat_id": int(chat_id)}
    return {"user_id": user_id}
