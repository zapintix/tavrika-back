import json
import uuid
from redis_config import redis_client as redis

REQUESTS_LIST = "reservation:requests"

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
        "phone": data["phone"],
        "table": data["table"],
        "date": data["date"],
        "time": data["time"],
        "status": "PENDING"
    }
    
    await redis.redis_client.set(reservation_key(res_id), json.dumps(reserv))

    await redis.redis_client.rpush(REQUESTS_LIST, res_id)

    return res_id