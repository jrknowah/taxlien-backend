"""Mississippi Secretary of State tax-forfeited land inventory.

Parcels that went unsold at a county tax sale and were never redeemed are
forfeited to the state and listed at https://www.sos.ms.gov/tfsearch/. That
page is backed by an ASP.NET web service (LandsSearch.asmx) which returns
records as '%'-delimited fields, rows joined by '^'.
"""
import time
from datetime import datetime

import httpx

SOURCE = "ms_sos_forfeited"
BASE_URL = "https://www.sos.ms.gov/tfsearch/LandsSearch.asmx"
PAGE_SIZE = 100

# Order of the county <select> on the search page; the service takes the
# 0-based position, not the name.
COUNTIES = [
    "Adams", "Alcorn", "Amite", "Attala", "Benton", "Bolivar", "Calhoun",
    "Carroll", "Chickasaw", "Choctaw", "Claiborne", "Clarke", "Clay",
    "Coahoma", "Copiah", "Covington", "DeSoto", "Forrest", "Franklin",
    "George", "Greene", "Grenada", "Hancock", "Harrison", "Hinds", "Holmes",
    "Humphreys", "Issaquena", "Itawamba", "Jackson", "Jasper", "Jefferson",
    "Jefferson Davis", "Jones", "Kemper", "Lafayette", "Lamar", "Lauderdale",
    "Lawrence", "Leake", "Lee", "Leflore", "Lincoln", "Lowndes", "Madison",
    "Marion", "Marshall", "Monroe", "Montgomery", "Neshoba", "Newton",
    "Noxubee", "Oktibbeha", "Panola", "Pearl River", "Perry", "Pike",
    "Pontotoc", "Prentiss", "Quitman", "Rankin", "Scott", "Sharkey",
    "Simpson", "Smith", "Stone", "Sunflower", "Tallahatchie", "Tate",
    "Tippah", "Tishomingo", "Tunica", "Union", "Walthall", "Warren",
    "Washington", "Wayne", "Webster", "Wilkinson", "Winston", "Yalobusha",
    "Yazoo",
]


def county_code(county: str) -> int:
    for i, name in enumerate(COUNTIES):
        if name.lower() == county.strip().lower():
            return i
    raise ValueError(f"Unknown Mississippi county: {county!r}")


def _blank_to_none(value: str):
    value = value.strip()
    return value or None


def _to_float(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_search_response(data: str, county: str) -> tuple[list[dict], int]:
    """Return (parcels, total_count) from a ProcessSearch payload."""
    rows, meta = data.rsplit("|", 1)
    total = int(meta.split("~")[0])
    parcels = []
    for row in rows.split("^"):
        f = row.split("%")
        if len(f) < 19 or not f[0]:
            continue
        twp = f"{f[6]}{f[7]}" if f[6] else None
        rng = f"{f[8]}{f[9]}" if f[8] else None
        owners = [o.strip() for o in f[18].split("~") if o.strip()]
        parcels.append({
            "source": SOURCE,
            "source_id": f[0],
            # Harrison comes back as "Harrison First Judicial District" etc.
            "county": county,
            "market_value": _to_float(f[3]),
            "sec": _blank_to_none(f[5]),
            "twp": twp,
            "rng": rng,
            "legal_description": _blank_to_none(f[10]),
            "address": _blank_to_none(" ".join(p for p in (f[11], f[12]) if p.strip())),
            "city": _blank_to_none(f[13]),
            "state": _blank_to_none(f[14]),
            "zip": _blank_to_none(f[15]),
            "parcel_number": _blank_to_none(f[16]),
            "ppin": _blank_to_none(f[17]),
            "owners": ", ".join(owners) or None,
            "status": "forfeited",
        })
    return parcels, total


def parse_detail_response(data: str) -> dict:
    """Extra fields only available from ProcessSearchDetail."""
    f = data.split("%")
    if len(f) < 32:
        return {}
    sale_date = None
    try:
        sale_date = datetime.strptime(f[30].strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        pass
    tax_year = int(f[31]) if f[31].strip().isdigit() else None
    return {
        "acres": _to_float(f[13]) or None,
        "legal_description": _blank_to_none(f[18]),
        "tax_sale_date": sale_date,
        "tax_year": tax_year,
    }


class SOSClient:
    def __init__(self, client: httpx.Client | None = None, delay: float = 0.25):
        self.client = client or httpx.Client(timeout=60)
        self.delay = delay  # be polite to a state server

    def _call(self, method: str, payload: dict) -> str:
        res = self.client.post(f"{BASE_URL}/{method}", json=payload)
        res.raise_for_status()
        if self.delay:
            time.sleep(self.delay)
        return res.json()["d"]

    def search_county(self, county: str) -> list[dict]:
        code = county_code(county)
        parcels: list[dict] = []
        page = 0
        while True:
            data = self._call("ProcessSearch", _search_payload(code, page))
            batch, total = parse_search_response(data, county)
            parcels.extend(batch)
            page += 1
            if not batch or len(parcels) >= total:
                return parcels

    def parcel_detail(self, source_id: str) -> dict:
        return parse_detail_response(self._call("ProcessSearchDetail", {"tmpParcelId": source_id}))


def _search_payload(county_code: int, page: int) -> dict:
    blank = ["tmpSection", "tmpTownship", "tmpTownshipDir", "tmpRange",
             "tmpRangeDir", "tmpSubdivision", "tmpLine1", "tmpLine2", "tmpCity",
             "tmpZipcode", "tmpParcelNum", "tmpPPIN", "tmpValueStart",
             "tmpValueEnd", "tmpAssessedOwner", "tmpLegalDesc"]
    payload = {k: "" for k in blank}
    payload.update({
        "tmpCounties": str(county_code),
        "tmpAddrSearchType": "C",
        "tmpLegalSearchType": "C",
        "startingNumber": page,  # page index, not a row offset
        "numberToDisplay": PAGE_SIZE,
    })
    return payload
