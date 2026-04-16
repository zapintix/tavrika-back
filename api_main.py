from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from bot.comands import ReservationBot
from datetime import datetime, timedelta
from redis_config.redis_helpers import get_user_data, set_user_data
from redis_config import redis_helpers
import hmac
import os
import json
import httpx
import hashlib
from urllib.parse import parse_qsl
from operator import itemgetter
from dotenv import load_dotenv

load_dotenv()

MAX_TOKEN = os.getenv("MAX_TOKEN")
MAX_API_BASE = "https://platform-api.max.ru"

app = FastAPI(title="Reservation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "https://dhn8pkql-5173.inc1.devtunnels.ms",
    "https://reserve.localcafe.ru"
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = ReservationBot(app)
class ReservationWebAppRequest(BaseModel):
    init_data: str = Field(alias="initData")
    booking_type: str = Field(alias="bookingType")
    date: str
    time: str
    guest_count: int = Field(alias="guestCount")
    table_id: str = Field(alias="tableId")
    table_number: str | int | None = Field(default=None, alias="tableNumber")
    guest_name: str = Field(alias="guestName")
    guest_phone: str = Field(alias="guestPhone")

class ReservationTableRequest(BaseModel):
    date: str
    time: str


class ReservationTableResponse(BaseModel):
    tableNumber: Optional[int] = None


class ReservationCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(alias="userId")
    date: str
    time: str
    guests: int
    table_id: str = Field(alias="tableId")
    table: str | int | None = None
    table_number: str | int | None = Field(default=None, alias="tableNumber")
    name: str | None = None
    guest_name: str | None = Field(default=None, alias="guestName")
    phone: str | None = None
    guest_phone: str | None = Field(default=None, alias="guestPhone")
    platform: str = "max"
    event_type: str | None = Field(default=None, alias="eventType")


def _normalize_name(raw_name: str | None) -> str | None:
    if not raw_name:
        return None

    normalized = " ".join(raw_name.split())
    if len(normalized) < 2:
        return None
    return normalized


async def _build_reservation_payload(req: ReservationCreateRequest) -> dict:
    stored_data = await get_user_data(req.user_id)
    stored_phone = stored_data.get("phone", "")

    name = _normalize_name(req.name or req.guest_name or stored_data.get("profile_name"))
    if not name:
        raise HTTPException(status_code=400, detail="Не удалось определить имя гостя.")

    phone = bot._normalize_phone(req.phone or req.guest_phone or stored_phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона.")

    reservation_date = bot._parse_date(req.date)
    if not reservation_date:
        raise HTTPException(status_code=400, detail="Некорректная дата брони.")

    reservation_time = bot._parse_time(req.time)
    if not reservation_time:
        raise HTTPException(status_code=400, detail="Некорректное время брони.")

    if not 1 <= req.guests <= 20:
        raise HTTPException(status_code=400, detail="Количество гостей должно быть от 1 до 20.")

    date_iso = reservation_date.isoformat()
    time_value = reservation_time.strftime("%H:%M")
    available_tables = await bot.get_available_tables(
        reservation_date=date_iso,
        reservation_time=time_value,
        guests=req.guests,
    )
    selected_table = next((table for table in available_tables if table["id"] == req.table_id), None)
    if not selected_table:
        raise HTTPException(status_code=409, detail="Выбранный стол уже недоступен.")

    preserved_data = {
        "profile_name": name,
        "phone": phone,
    }
    chat_id = stored_data.get("chat_id")
    if chat_id is not None:
        preserved_data["chat_id"] = chat_id
    await set_user_data(req.user_id, preserved_data)

    return {
        "user_id": req.user_id,
        "platform": (req.platform or "max").lower(),
        "eventType": req.event_type or "max_bot",
        "name": name,
        "phone": phone,
        "guests": req.guests,
        "table": req.table or req.table_number or selected_table["number"],
        "tableId": selected_table["id"],
        "date": date_iso,
        "time": time_value,
    }


@app.post("/api/reservations/table")
async def get_reserved_tables(req: ReservationTableRequest):
    day_reservations = await bot.fetch_day_reservations(req.date)

    requested_time = datetime.fromisoformat(
        f"{req.date}T{req.time}"
    )

    reserved_table_ids: set[str] = set()
    if len(day_reservations) != 0:
        for r in day_reservations:
            print(r)
            start = datetime.fromisoformat(r["estimatedStartTime"])
            duration = r.get("durationInMinutes", 120) 
            end = start + timedelta(minutes=duration)

            if start <= requested_time < end:
                reserved_table_ids.update(r.get("tableIds", []))
            print(reserved_table_ids)

    return {
        "reservedTableIds": list(reserved_table_ids)
    }

def _validate_app_data(app_data: str) -> bool:
    params = list(dict(parse_qsl(app_data, keep_blank_values=True)).items())
    original_hash = next((value for key, value in params if key == "hash"), None)

    if not original_hash:
        return False

    params_to_sign = sorted(
        [(k, v) for k, v in params if k != "hash"],
        key=itemgetter(0)
    )

    launch_params = "\n".join(f"{k}={v}" for k, v in params_to_sign)

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=MAX_TOKEN.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        key=secret_key,
        msg=launch_params.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(calculated_hash, original_hash)


def _parse_validated_app_data(app_data: str) -> dict:
    if not _validate_app_data(app_data):
        raise HTTPException(status_code=403, detail="initData не прошло валидацию")

    params = dict(parse_qsl(app_data, keep_blank_values=True))

    if params.get("user"):
        params["user"] = json.loads(params["user"])

    if params.get("chat"):
        params["chat"] = json.loads(params["chat"])

    return params


async def send_max_message(*, chat_id: int | None, user_id: int | None, text: str) -> dict:
    if not chat_id and not user_id:
        raise HTTPException(status_code=400, detail="Не удалось определить chat_id или user_id")

    params = {}
    if chat_id:
        params["chat_id"] = chat_id
    else:
        params["user_id"] = user_id

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{MAX_API_BASE}/messages",
            params=params,
            headers={
                "Authorization": MAX_TOKEN,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "notify": True,
            },
        )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"MAX API error: {response.status_code} {response.text}",
        )

    return response.json()

# @app.post("/api/reservations")
# async def create_reservation(req: ReservationCreateRequest):
#     reservation_data = await _build_reservation_payload(req)
#     reservation_id = await redis_helpers.save_reservation(reservation_data)

#     return {
#         "status": "created",
#         "reservationId": reservation_id,
#         "message": "Заявка создана и отправлена администраторам.",
#         "reservation": reservation_data,
#     }

@app.post("/api/reservations/webapp")
async def create_webapp_reservation(req: ReservationWebAppRequest):
    app_data = _parse_validated_app_data(req.init_data)

    user = app_data.get("user") or {}
    chat = app_data.get("chat") or {}

    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="В initData нет user.id")

    stored_data = await get_user_data(user_id)
    preserved_data = dict(stored_data)

    if chat.get("id") is not None:
        preserved_data["chat_id"] = chat["id"]

    await set_user_data(user_id, preserved_data)

    internal_req = ReservationCreateRequest(
        userId=user_id,
        date=req.date,
        time=req.time,
        guests=req.guest_count,
        tableId=req.table_id,
        tableNumber=req.table_number,
        guestName=req.guest_name,
        guestPhone=req.guest_phone,
        platform="max",
        eventType="max_web_app",
    )

    reservation_data = await _build_reservation_payload(internal_req)
    reservation_id = await redis_helpers.save_reservation(reservation_data)

    confirmation_text = "\n".join([
        "Бронь создана",
        f"Гость: {reservation_data['name']}",
        f"Телефон: {reservation_data['phone']}",
        f"Дата: {reservation_data['date']}",
        f"Время: {reservation_data['time']}",
        f"Стол: №{reservation_data['table']}",
        f"Гостей: {reservation_data['guests']}",
    ])

    await send_max_message(
        chat_id=chat.get("id"),
        user_id=user_id,
        text=confirmation_text,
    )

    return {
        "status": "created",
        "reservationId": reservation_id,
        "message": "Бронь создана и подтверждение отправлено в MAX.",
        "reservation": reservation_data,
    }

