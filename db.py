import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
    source            TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    county            TEXT NOT NULL,
    parcel_number     TEXT,
    ppin              TEXT,
    address           TEXT,
    city              TEXT,
    state             TEXT,
    zip               TEXT,
    owners            TEXT,
    market_value      REAL,
    legal_description TEXT,
    sec               TEXT,
    twp               TEXT,
    rng               TEXT,
    acres             REAL,
    tax_year          INTEGER,
    tax_sale_date     TEXT,
    status            TEXT,
    active            INTEGER NOT NULL DEFAULT 1,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS parcels_county ON parcels (county, active);

CREATE TABLE IF NOT EXISTS liens (
    source            TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    county            TEXT NOT NULL,
    tax_year          INTEGER NOT NULL,
    parcel_number     TEXT,
    ppin              TEXT,
    owner             TEXT,
    mailing_address   TEXT,
    property_address  TEXT,
    legal_description TEXT,
    acres             REAL,
    true_value        REAL,
    face_amount       REAL,
    sale_date         TEXT,
    buyer             TEXT,
    overbid           REAL,
    status            TEXT NOT NULL,
    source_url        TEXT,
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS liens_county_year ON liens (county, tax_year, status);
"""

COLUMNS = [
    "source", "source_id", "county", "parcel_number", "ppin", "address", "city",
    "state", "zip", "owners", "market_value", "legal_description", "sec", "twp",
    "rng", "acres", "tax_year", "tax_sale_date", "status",
]


def db_path() -> str:
    return os.getenv("DATABASE_PATH", "taxliens.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def existing_ids(conn, source: str, county: str) -> set[str]:
    rows = conn.execute(
        "SELECT source_id FROM parcels WHERE source = ? AND county = ?", (source, county)
    )
    return {r["source_id"] for r in rows}


def upsert_parcels(conn, parcels: list[dict], seen_at: str) -> None:
    cols = ", ".join(COLUMNS)
    marks = ", ".join("?" for _ in COLUMNS)
    # COALESCE keeps detail-only fields from an earlier sync when this
    # sync only fetched the search listing.
    updates = ", ".join(
        f"{c} = COALESCE(excluded.{c}, {c})" for c in COLUMNS if c not in ("source", "source_id")
    )
    conn.executemany(
        f"""INSERT INTO parcels ({cols}, active, first_seen, last_seen)
            VALUES ({marks}, 1, ?, ?)
            ON CONFLICT (source, source_id) DO UPDATE SET
                {updates}, active = 1, last_seen = excluded.last_seen""",
        [[p.get(c) for c in COLUMNS] + [seen_at, seen_at] for p in parcels],
    )


def deactivate_missing(conn, source: str, county: str, seen_ids: set[str]) -> int:
    """Parcels no longer listed were sold or redeemed; keep them for history."""
    active = conn.execute(
        "SELECT source_id FROM parcels WHERE source = ? AND county = ? AND active = 1",
        (source, county),
    )
    missing = [(source, r["source_id"]) for r in active if r["source_id"] not in seen_ids]
    conn.executemany("UPDATE parcels SET active = 0 WHERE source = ? AND source_id = ?", missing)
    return len(missing)


def query_parcels(conn, *, county=None, source=None, min_value=None, max_value=None,
                  include_inactive=False, limit=100, offset=0) -> tuple[list[dict], int]:
    where, args = [], []
    if not include_inactive:
        where.append("active = 1")
    if county:
        where.append("county = ? COLLATE NOCASE")
        args.append(county)
    if source:
        where.append("source = ?")
        args.append(source)
    if min_value is not None:
        where.append("market_value >= ?")
        args.append(min_value)
    if max_value is not None:
        where.append("market_value <= ?")
        args.append(max_value)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM parcels {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM parcels {clause} ORDER BY county, market_value DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    )
    return [dict(r) for r in rows], total


LIEN_COLUMNS = [
    "source", "source_id", "county", "tax_year", "parcel_number", "ppin", "owner",
    "mailing_address", "property_address", "legal_description", "acres",
    "true_value", "face_amount", "sale_date", "buyer", "overbid", "status", "source_url",
]


def upsert_liens(conn, liens: list[dict], seen_at: str) -> None:
    cols = ", ".join(LIEN_COLUMNS)
    marks = ", ".join("?" for _ in LIEN_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in LIEN_COLUMNS if c not in ("source", "source_id"))
    conn.executemany(
        f"""INSERT INTO liens ({cols}, first_seen, last_seen) VALUES ({marks}, ?, ?)
            ON CONFLICT (source, source_id) DO UPDATE SET {updates}, last_seen = excluded.last_seen""",
        [[lien.get(c) for c in LIEN_COLUMNS] + [seen_at, seen_at] for lien in liens],
    )


def query_liens(conn, *, county=None, tax_year=None, status=None, min_face=None,
                max_face=None, limit=100, offset=0) -> tuple[list[dict], int]:
    where, args = [], []
    for col, op, val in (
        ("county", "= ? COLLATE NOCASE", county),
        ("tax_year", "= ?", tax_year),
        ("status", "= ?", status),
        ("face_amount", ">= ?", min_face),
        ("face_amount", "<= ?", max_face),
    ):
        if val is not None:
            where.append(f"{col} {op}")
            args.append(val)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM liens {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM liens {clause} ORDER BY county, tax_year DESC, face_amount DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    )
    return [dict(r) for r in rows], total
