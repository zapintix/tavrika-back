import json
from redis_config import redis_client as redis

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