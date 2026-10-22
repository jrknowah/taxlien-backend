"""Hinds County tax sale files.

The Tax Collector posts each sale's parcel list as zipped Excel files on
https://www.co.hinds.ms.us/pgs/taxsalefiles.asp:
  RP0095-<sale year>-Final-TaxSale-In.zip  parcels going to sale
  RP0095-<sale year>-Final-Results.zip     same list with buyer and overbid
"""
import re

import pandas as pd

from .county_common import clean, http_client, join, mississippi_sale_date, read_excel_bytes, to_float

SOURCE = "hinds_tax_sale"
COUNTY = "Hinds"
INDEX_URL = "https://www.co.hinds.ms.us/pgs/taxsalefiles.asp"
FILE_RE = re.compile(r"RP0095-(\d{4})-Final-(Results|TaxSale-In)\.zip", re.I)
STATE = "STATE OF MISSISSIPPI"
# The county server only offers this SHA-1 CBC suite, which Python excludes by default.
LEGACY_CIPHERS = "ECDHE-RSA-AES256-SHA"


def find_files(index_html: str) -> list[tuple[str, bool]]:
    """(url, is_results) for each sale file, pre-sale lists first so results win."""
    found = {}
    for m in re.finditer(r'href="([^"]+)"', index_html):
        url = m.group(1)
        fm = FILE_RE.search(url)
        if fm:
            if not url.startswith("http"):
                url = "https://www.co.hinds.ms.us/" + url.lstrip("/")
            found[url] = fm.group(2).lower() == "results"
    return sorted(found.items(), key=lambda kv: kv[1])


def _location(raw) -> str | None:
    # "03702      OLD CANTON RD" -> "3702 OLD CANTON RD"; house number 0 means none.
    loc = clean(raw)
    if not loc:
        return None
    number, _, street = loc.partition(" ")
    if number.isdigit():
        number = str(int(number)) if int(number) else ""
        return join(number, street)
    return loc


def _status(buyer: str | None, is_results: bool) -> str:
    if not is_results:
        return "offered"
    if not buyer:
        return "not_sold"  # paid or withdrawn before the sale
    return "struck_to_state" if buyer.upper() == STATE else "sold"


def parse(df: pd.DataFrame, is_results: bool, source_url: str | None = None) -> list[dict]:
    liens = []
    for r in df.to_dict(orient="records"):
        parcel = clean(r.get("PARCEL"))
        year = clean(r.get("tax_year"))
        if not parcel or not (year and year.isdigit()):
            continue
        tax_year = int(year)
        buyer = clean(r.get("sold_to")) if is_results else None
        liens.append({
            "source": SOURCE,
            # Lot-cleanup assessments are sold as a separate lien on the same parcel.
            "source_id": f"{tax_year}-{parcel}-{clean(r.get('type_tax')) or '1'}",
            "county": COUNTY,
            "tax_year": tax_year,
            "parcel_number": clean(r.get("PARCEL_formatted")) or parcel,
            "ppin": None,
            "owner": clean(r.get("NAME")),
            "mailing_address": join(r.get("ADDR1"), r.get("ADDR2"), r.get("ADDR3"), sep=", "),
            "property_address": _location(r.get("LOCATION")),
            "legal_description": join(*(r.get(f"DESC{i}") for i in range(1, 9))),
            "acres": None,
            "true_value": to_float(r.get("TRUE_VALUE")),
            "face_amount": to_float(r.get("TOTAL")),
            "sale_date": mississippi_sale_date(tax_year).isoformat(),
            "buyer": buyer,
            "overbid": to_float(r.get("EXCESS_BID")) if is_results else None,
            "status": _status(buyer, is_results),
            "source_url": source_url,
        })
    return liens


def fetch(client=None) -> list[dict]:
    client = client or http_client(LEGACY_CIPHERS)
    res = client.get(INDEX_URL)
    res.raise_for_status()
    liens = []
    for url, is_results in find_files(res.text):
        file_res = client.get(url)
        file_res.raise_for_status()
        liens.extend(parse(read_excel_bytes(file_res.content), is_results, url))
    return liens
