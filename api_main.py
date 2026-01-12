from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from bot.comands import ReservationBot

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
    print("Гойда")
    day_reservations = await bot.fetch_day_reservations(req.date)

    reserved_table_ids: set[str] = set()

    for r in day_reservations:
        start = r.get("estimatedStartTime")
        duration = r.get("durationInMinutes")
        table_ids = r.get("tableIds", [])

        start_time = start[11:16]

        print(start_time)
        print(req.time)
        if start_time == req.time:
            reserved_table_ids.update(table_ids)
        print("reservedTableIds:", list(reserved_table_ids))
    return {
        "reservedTableIds": list(reserved_table_ids)
    }
