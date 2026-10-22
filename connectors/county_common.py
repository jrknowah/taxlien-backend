import io
import re
import ssl
import zipfile
from datetime import date, timedelta

import httpx
import pandas as pd

# Some county sites reject requests without a browser-like user agent.
USER_AGENT = "Mozilla/5.0 (compatible; taxlien-backend/1.0)"


def http_client(legacy_ciphers: str | None = None) -> httpx.Client:
    """legacy_ciphers re-enables extra cipher suites for servers that only
    offer ones Python disables by default. Certificates are still verified."""
    verify = True
    if legacy_ciphers:
        verify = ssl.create_default_context()
        verify.set_ciphers(f"DEFAULT:{legacy_ciphers}")
    return httpx.Client(timeout=120, follow_redirects=True, verify=verify,
                        headers={"User-Agent": USER_AGENT})


def mississippi_sale_date(tax_year: int) -> date:
    """Statutory sale: last Monday of August of the year after the tax year."""
    d = date(tax_year + 1, 8, 31)
    return d - timedelta(days=d.weekday())  # Monday is 0


def read_excel_bytes(content: bytes) -> pd.DataFrame:
    """Read an .xlsx, or the first .xlsx inside a .zip."""
    if content[:2] == b"PK" and not _is_xlsx(content):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".xlsx"))
            content = zf.read(name)
    return pd.read_excel(io.BytesIO(content), dtype=str)


def _is_xlsx(content: bytes) -> bool:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        return "[Content_Types].xml" in zf.namelist()


def clean(value) -> str | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def to_float(value) -> float | None:
    try:
        f = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def join(*values, sep=" ") -> str | None:
    return clean(sep.join(str(v) for v in values if clean(v)))
