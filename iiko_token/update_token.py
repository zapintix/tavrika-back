import requests
from dotenv import load_dotenv
import os

load_dotenv()

def update_iiko_token(key:str):
    headers = {
        "Content-Type": "application/json"
    }

    json = {
        "apiLogin": key
    }

    response = requests.post(os.getenv("IIKO_TOKEN_URL"), json=json, headers=headers)
    if response.status_code == 200:
        response.raise_for_status()
        data = response.json()
        token = data['token']
        return token
    else:
        return(response.status_code, response.text)
