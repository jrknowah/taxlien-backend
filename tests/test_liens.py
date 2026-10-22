import io
import zipfile
from datetime import date

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import analysis
import db
import sync
from connectors import hinds, jackson
from connectors.county_common import mississippi_sale_date, read_excel_bytes

HINDS_ROWS = [
    # Column names match the county's RP0095 files.
    {"PARCEL": "00010006000", "PARCEL_formatted": "1-6", "type_tax": "1", "tax_year": "2024",
     "TOTAL": "4198.79", "TRUE_VALUE": "225080", "NAME": "DOE JOHN", "ADDR1": "1 MAIN ST",
     "ADDR2": "JACKSON MS 39216", "LOCATION": "03702      OLD CANTON RD", "DESC1": "LOT 6",
     "DESC2": "WOODLAND HILLS", "EXCESS_BID": "364", "sold_to": "FIG 25 LLC"},
    {"PARCEL": "00390056000", "PARCEL_formatted": "39-56", "type_tax": "2", "tax_year": "2024",
     "TOTAL": "300", "LOCATION": "00000      GLENWAY DR", "sold_to": "STATE OF MISSISSIPPI"},
    {"PARCEL": "00390056000", "PARCEL_formatted": "39-56", "type_tax": "1", "tax_year": "2024",
     "TOTAL": "58.61"},
]

JACKSON_ROWS = [
    {"sale_sequence": "1", "parcel_number": "00010640.075", "ArVKey": "7266753", "tax_year": "2025",
     "name": "DOE JANE", "ppin": "85574", "lgd1": "COM NW COR S 89*E 88", "lgd2": "1.13' TO POB",
     "acres": "1", "total_tax_cost": "854.34"},
    {"sale_sequence": "2", "parcel_number": "00010640.075", "ArVKey": "7308202", "tax_year": "2025",
     "name": "DOE JANE", "ppin": "85574", "acres": "1", "total_tax_cost": "312"},
]


def xlsx_bytes(rows) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def zipped(content: bytes, name="list.xlsx") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


def test_sale_date_is_last_monday_of_august():
    assert mississippi_sale_date(2024) == date(2025, 8, 25)
    assert mississippi_sale_date(2025) == date(2026, 8, 31)


def test_read_excel_bytes_handles_xlsx_and_zip():
    raw = xlsx_bytes(JACKSON_ROWS)
    assert len(read_excel_bytes(raw)) == 2
    assert len(read_excel_bytes(zipped(raw))) == 2


def test_hinds_find_files_puts_results_last():
    page = '''<a href="https://www.co.hinds.ms.us/download/RP0095-2025-Final-Results.zip">r</a>
              <a href="/download/RP0095-2026-Final-TaxSale-In.zip">in</a>
              <a href="/download/RPTS44-2025-Dist1.pdf">pdf</a>'''
    assert hinds.find_files(page) == [
        ("https://www.co.hinds.ms.us/download/RP0095-2026-Final-TaxSale-In.zip", False),
        ("https://www.co.hinds.ms.us/download/RP0095-2025-Final-Results.zip", True),
    ]


def test_hinds_parse_results():
    liens = hinds.parse(pd.DataFrame(HINDS_ROWS).astype(object), is_results=True)
    assert [l["status"] for l in liens] == ["sold", "struck_to_state", "not_sold"]
    sold = liens[0]
    assert sold["source_id"] == "2024-00010006000-1"
    assert sold["parcel_number"] == "1-6"
    assert sold["property_address"] == "3702 OLD CANTON RD"
    assert sold["mailing_address"] == "1 MAIN ST, JACKSON MS 39216"
    assert sold["legal_description"] == "LOT 6 WOODLAND HILLS"
    assert (sold["face_amount"], sold["overbid"], sold["buyer"]) == (4198.79, 364.0, "FIG 25 LLC")
    assert sold["sale_date"] == "2025-08-25"
    assert liens[1]["property_address"] == "GLENWAY DR"
    # Same parcel, different lien types, distinct keys.
    assert liens[1]["source_id"] != liens[2]["source_id"]


def test_hinds_parse_presale_list_ignores_buyer_columns():
    liens = hinds.parse(pd.DataFrame(HINDS_ROWS), is_results=False)
    assert {l["status"] for l in liens} == {"offered"}
    assert liens[0]["buyer"] is None and liens[0]["overbid"] is None


def test_jackson_find_files_and_parse():
    page = '''<a href="/DocumentCenter/View/1618">Tax Sale List for 2025 Real Property Taxes - Preliminary List</a>
              <a href="/DocumentCenter/View/99">Payment Instructions</a>'''
    assert jackson.find_files(page) == ["https://www.co.jackson.ms.us/DocumentCenter/View/1618"]
    liens = jackson.parse(pd.DataFrame(JACKSON_ROWS))
    assert [l["source_id"] for l in liens] == ["7266753", "7308202"]
    assert liens[0]["legal_description"] == "COM NW COR S 89*E 881.13' TO POB"
    assert (liens[0]["face_amount"], liens[0]["acres"], liens[0]["ppin"]) == (854.34, 1.0, "85574")
    assert liens[0]["status"] == "offered"


def test_lien_metrics():
    m = analysis.lien_metrics(1000.0, 100.0, "2025-08-25", as_of=date(2026, 2, 25))
    assert m["months_elapsed"] == 6
    assert m["accrued_interest"] == 90.0
    assert m["redemption_amount"] == 1090.0
    assert m["return_to_date"] == round(90 / 1100, 4)
    assert m["redemption_deadline"] == "2027-08-25"
    assert m["in_redemption_period"] is True
    assert m["max_interest"] == 360.0
    # Interest stops at the redemption deadline.
    late = analysis.lien_metrics(1000.0, 0, "2025-08-25", as_of=date(2030, 1, 1))
    assert late["months_elapsed"] == 24 and late["in_redemption_period"] is False
    # Not yet sold: nothing accrued.
    assert analysis.lien_metrics(1000.0, None, "2026-08-31", as_of=date(2026, 1, 1))["accrued_interest"] == 0
    assert analysis.lien_metrics(None, None, "2026-08-31") == {}


def county_client():
    files = {
        "/pgs/taxsalefiles.asp": b'<a href="/download/RP0095-2025-Final-Results.zip">r</a>',
        "/download/RP0095-2025-Final-Results.zip": zipped(xlsx_bytes(HINDS_ROWS)),
        "/376/Annual-Sale-of-Delinquent-Taxes": b'<a href="/DocumentCenter/View/1618">Tax Sale List for 2025</a>',
        "/DocumentCenter/View/1618": xlsx_bytes(JACKSON_ROWS),
    }
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=files[req.url.path])))


@pytest.fixture
def lien_db(tmp_path, monkeypatch):
    path = str(tmp_path / "liens.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    conn = db.connect(path)
    yield conn
    conn.close()


def test_sync_liens_and_endpoint(lien_db):
    stats = sync.sync_liens(["Hinds", "Jackson", "Monroe"], conn=lien_db, client=county_client())
    assert stats == {"Hinds": {"liens": 3}, "Jackson": {"liens": 2}}
    # Re-running updates in place.
    sync.sync_liens(["Hinds"], conn=lien_db, client=county_client())
    assert lien_db.execute("SELECT COUNT(*) FROM liens").fetchone()[0] == 5

    from main import app

    api = TestClient(app)
    body = api.get("/liens", params={"county": "hinds", "status": "sold"}).json()
    assert body["total"] == 1
    assert body["results"][0]["metrics"]["redemption_deadline"] == "2027-08-25"
    assert api.get("/liens", params={"min_face": 800}).json()["total"] == 2


def test_one_failing_county_does_not_stop_others(lien_db):
    def handler(req):
        if req.url.host == "www.co.hinds.ms.us":
            return httpx.Response(500)
        return county_client().get(str(req.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    stats = sync.sync_liens(["Hinds", "Jackson"], conn=lien_db, client=client)
    assert "error" in stats["Hinds"]
    assert stats["Jackson"] == {"liens": 2}
