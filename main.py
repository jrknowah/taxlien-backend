# backend/main.py
import logging
import os
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import db
import sync

log = logging.getLogger("main")

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
PREVIEW_ROWS = 5

# Comma-separated list, e.g. "http://localhost:5173,https://app.example.com"
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# Cron expression for the background sync, e.g. "0 6 * * 1" (Mondays 06:00 UTC).
# Unset disables it. With several uvicorn workers each would run it, so use
# one worker or run `python sync.py` from cron instead.
SYNC_CRON = os.getenv("SYNC_CRON")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if SYNC_CRON:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(_scheduled_sync, CronTrigger.from_crontab(SYNC_CRON, timezone="UTC"))
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def _scheduled_sync():
    try:
        sync.sync_ms_sos()
    except Exception:
        log.exception("Scheduled sync failed")


app = FastAPI(title="Tax Lien Analyzer API", lifespan=lifespan)

# Allow frontend requests (CORS). Wildcard origins can't be combined with
# credentials, so origins are listed explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "API is running!"}


@app.get("/parcels")
def list_parcels(
    county: str | None = None,
    source: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    conn = db.connect()
    try:
        rows, total = db.query_parcels(
            conn, county=county, source=source, min_value=min_value, max_value=max_value,
            include_inactive=include_inactive, limit=limit, offset=offset,
        )
    finally:
        conn.close()
    return {"total": total, "limit": limit, "offset": offset, "results": rows}


# Plain `def` so FastAPI runs the blocking pandas parse in a worker thread.
@app.post("/upload")
def upload_file(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    try:
        df = pd.read_csv(file.file)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    # NaN isn't valid JSON; send empty cells as null.
    head = df.head(PREVIEW_ROWS)
    preview = head.astype(object).where(head.notna(), None)
    return {
        "row_count": len(df),
        "columns": df.columns.tolist(),
        "preview": preview.to_dict(orient="records"),
    }
