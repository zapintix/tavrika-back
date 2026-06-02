import json
import uuid
from redis_config import redis_client as redis

CHANNEL = "new-reservations"
REQUESTS_LIST = "reservation:requests"

async def listen_new_reservations(callback):
    pubsub = redis.redis_client.pubsub()
    await pubsub.subscribe(CHANNEL)
    async for message in pubsub.listen():
        if message["type"] == "message":
            data = message["data"]
            await callback(data)


def redis_key(user_id:int) -> str:
    return f"reservation:{user_id}"

async def get_user_data(user_id:int) -> dict:
    data = await redis.redis_client.get(redis_key(user_id))
    return json.loads(data) if data else {}

async def set_user_data(user_id:int, data:dict):
    await redis.redis_client.set(
        redis_key(user_id),
        json.dumps(data),
        ex=60 * 30
        )

async def clear_user_data(user_id:int):
    await redis.redis_client.delete(redis_key(user_id))

def reservation_key(res_id: str) -> str:
    return f"reservation:request:{res_id}"

async def save_reservation(data:dict)->str:
    res_id = str(uuid.uuid4())
    platform = data.get("platform", "telegram")

    reserv = {
        "id": res_id,
        "user_id": data.get("user_id"),
        "platform": platform,
        "eventType": data.get("eventType", "telegram_bot"),
        "name":data["name"],
        "phone": data["phone"],
        "guests": data["guests"],
        "table": data["table"],
        "tableId":data["tableId"],
        "date": data["date"],
        "time": data["time"],
        "occasion": data.get("occasion") or "-",
        "status": "PENDING",
        "confirmation_status": "NOT_REQUIRED" if platform == "site" else "WAITING",
        "confirmation_message_id": None,
        "admin_notifications": {},
    }
    
    await redis.redis_client.set(reservation_key(res_id), json.dumps(reserv))

    await redis.redis_client.rpush(REQUESTS_LIST, res_id)

    await redis.redis_client.publish("new-reservations", json.dumps(reserv))

    return res_id

async def get_reservation_by_id(res_id: str) -> dict | None:
    data = await redis.redis_client.get(reservation_key(res_id))
    if not data:
        return None
    return json.loads(data)

async def get_iikoId_by_id(res_id: str) -> str | None:
    data = await redis.redis_client.get(reservation_key(res_id))
    if not data:
        return None

    reservation = json.loads(data)
    return reservation.get("id_iiko")


async def delete_reservation_by_id(res_id: str):
    await redis.redis_client.delete(reservation_key(res_id))

async def update_reservation_status(res_id:str, new_status:str, id_iiko: str):
    key = reservation_key(res_id)

    data = await redis.redis_client.get(key)
    if not data:
        return False
    
    reservation = json.loads(data)

    reservation["status"] = new_status

    if id_iiko is not None:
        reservation["id_iiko"] = id_iiko
    await redis.redis_client.set(key, json.dumps(reservation))
    return True

async def update_reservation_confirmation(
    res_id: str,
    status: str,
    message_id: str | int | None = None,
):
    key = reservation_key(res_id)

    data = await redis.redis_client.get(key)
    if not data:
        return False

    reservation = json.loads(data)

    reservation["confirmation_status"] = status

    if message_id is not None:
        reservation["confirmation_message_id"] = message_id

    await redis.redis_client.set(key, json.dumps(reservation))
    return True

async def update_reservation_admin_notification(
    res_id: str,
    admin_id: int,
    message_id: str | int,
):
    key = reservation_key(res_id)

    data = await redis.redis_client.get(key)
    if not data:
        return False

    reservation = json.loads(data)
    notifications = reservation.get("admin_notifications") or {}
    notifications[str(admin_id)] = message_id
    reservation["admin_notifications"] = notifications

    await redis.redis_client.set(key, json.dumps(reservation))
    return True

async def clear_reservation_admin_notifications(res_id: str):
    key = reservation_key(res_id)

    data = await redis.redis_client.get(key)
    if not data:
        return False

    reservation = json.loads(data)
    reservation["admin_notifications"] = {}

    await redis.redis_client.set(key, json.dumps(reservation))
    return True

async def get_status_by_id(res_id: str):
    data = await redis.redis_client.get(reservation_key(res_id))
    if not data:
        return None
    
    reservation = json.loads(data)
    return reservation["status"]

async def get_confirmation_status_by_id(res_id: str):
    data = await redis.redis_client.get(reservation_key(res_id))
    if not data:
        return None
    
    reservation = json.loads(data)
    return reservation["confirmation_status"]
