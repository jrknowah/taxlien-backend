# backend/main.py
import os

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
PREVIEW_ROWS = 5

# Comma-separated list, e.g. "http://localhost:5173,https://app.example.com"
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

app = FastAPI(title="Tax Lien Analyzer API")

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
