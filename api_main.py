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

class ReservationRequest(BaseModel):
    date: str
    tableNumber: Optional[int] = None

class ReservationResponse(BaseModel):
    reservedTimes: List[str]

class ReservationTableRequest(BaseModel):
    date: str
    time: str

class ReservationTableResponse(BaseModel):
    tableNumber: Optional[int] = None


# @app.post("/api/reservations", response_model=ReservationResponse)
# async def get_reservations(req: ReservationRequest):
#     day_reservations = await bot.fetch_day_reservations(req.date)
    
#     print("day_reservations: ", day_reservations)
#     reservations_data = {}
    
#     for r in day_reservations:
#         table_ids = r.get("tableIds")
#         est_time = r.get("estimatedStartTime")
#         if not est_time:
#             continue

#         time_str = est_time[11:16]

#         for t_id in table_ids:
#             if t_id not in reservations_data:
#                 reservations_data[t_id] = []
#             reservations_data[t_id].append(time_str)
    
#     reserved_times: List[str] = []
#     if req.tableNumber is not None:
#         reserved_times = reservations_data.get(req.tableNumber, [])
#     else:
#         times_set = set()
#         for t_list in reservations_data.values():
#             times_set.update(t_list)
#         reserved_times = sorted(list(times_set))
#     print("reservedTimes:",  reserved_times)
#     return {"reservedTimes": reserved_times}

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
