from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from bot.comands import ReservationBot
from datetime import datetime, timedelta

app = FastAPI(title="Reservation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = ReservationBot(app)

class ReservationTableRequest(BaseModel):
    date: str
    time: str

class ReservationTableResponse(BaseModel):
    tableNumber: Optional[int] = None

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
