import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://platform-api.max.ru"
TOKEN = os.getenv("MAX_TOKEN")
START_TEXT = "Привет из таврики"
BUTTON_TEXT = "Таврика"
BUTTON_URL = "https://reserve.localcafe.ru"
HEADERS = {"Authorization": TOKEN, "Content-Type": "application/json"}


def send_start(chat_id):
    if not chat_id:
        return

    response = requests.post(
        f"{API_URL}/messages",
        headers=HEADERS,
        params={"chat_id": chat_id},
        json={
            "text": START_TEXT,
            "attachments": [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [[{"type": "link", "text": BUTTON_TEXT, "url": BUTTON_URL}]]
                    },
                }
            ],
        },
        timeout=30,
    )
    response.raise_for_status()


def handle_update(update):
    if update.get("update_type") != "message_created":
        return

    message = update.get("message") or {}
    text = ((message.get("body") or {}).get("text") or "").strip().lower()

    if text == "Привет" or text == "привет":
        send_start((message.get("recipient") or {}).get("chat_id"))


def main():
    print("Бот Max запущен....")
    if not TOKEN:
        raise RuntimeError("MAX_TOKEN is not set")

    marker = None

    while True:
        try:
            params = {
                "limit": 100,
                "timeout": 30,
                "types": "message_created",
            }

            if marker is not None:
                params["marker"] = marker

            response = requests.get(
                f"{API_URL}/updates",
                headers=HEADERS,
                params=params,
                timeout=params["timeout"] + 10,
            )
            response.raise_for_status()
            data = response.json()

            for update in data.get("updates", []):
                handle_update(update)

            marker = data.get("marker", marker)
        except requests.RequestException:
            time.sleep(5)


if __name__ == "__main__":
    main()
