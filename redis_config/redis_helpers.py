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

    reserv = {
        "id": res_id,
        "user_id": data["user_id"],
        "name":data["name"],
        "phone": data["phone"],
        "table": data["table"],
        "date": data["date"],
        "time": data["time"],
        "status": "PENDING"
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