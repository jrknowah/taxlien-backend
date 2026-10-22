"""Jackson County delinquent tax sale list.

The Tax Collector links the (preliminary) list from
https://www.co.jackson.ms.us/376/Annual-Sale-of-Delinquent-Taxes as
"Tax Sale List for <year> Real Property Taxes". Only the pre-sale list is
published, not results.
"""
import html
import re

import pandas as pd

from .county_common import clean, http_client, mississippi_sale_date, read_excel_bytes, to_float

SOURCE = "jackson_tax_sale"
COUNTY = "Jackson"
BASE_URL = "https://www.co.jackson.ms.us"
INDEX_URL = f"{BASE_URL}/376/Annual-Sale-of-Delinquent-Taxes"
LINK_RE = re.compile(r'<a[^>]*href="([^"]*DocumentCenter/View/[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)


def find_files(index_html: str) -> list[str]:
    urls = []
    for href, text in LINK_RE.findall(index_html):
        text = re.sub(r"<[^>]+>", "", html.unescape(text))
        if re.search(r"tax sale list", text, re.I):
            urls.append(href if href.startswith("http") else BASE_URL + href)
    return urls


def parse(df: pd.DataFrame, source_url: str | None = None) -> list[dict]:
    liens = []
    for r in df.to_dict(orient="records"):
        bill = clean(r.get("ArVKey"))
        year = clean(r.get("tax_year"))
        if not bill or not (year and year.isdigit()):
            continue
        tax_year = int(year)
        # Legal description is split into fixed-width chunks, often mid-word.
        legal = "".join(str(r.get(f"lgd{i}")) for i in range(1, 10) if clean(r.get(f"lgd{i}")))
        liens.append({
            "source": SOURCE,
            "source_id": bill,  # one row per tax bill; a parcel can have several
            "county": COUNTY,
            "tax_year": tax_year,
            "parcel_number": clean(r.get("parcel_number")),
            "ppin": clean(r.get("ppin")),
            "owner": clean(r.get("name")),
            "mailing_address": None,
            "property_address": None,
            "legal_description": clean(legal),
            "acres": to_float(r.get("acres")),
            "true_value": None,
            "face_amount": to_float(r.get("total_tax_cost")),
            "sale_date": mississippi_sale_date(tax_year).isoformat(),
            "buyer": None,
            "overbid": None,
            "status": "offered",
            "source_url": source_url,
        })
    return liens


def fetch(client=None) -> list[dict]:
    client = client or http_client()
    res = client.get(INDEX_URL)
    res.raise_for_status()
    liens = []
    for url in find_files(res.text):
        file_res = client.get(url)
        file_res.raise_for_status()
        liens.extend(parse(read_excel_bytes(file_res.content), url))
    return liens
