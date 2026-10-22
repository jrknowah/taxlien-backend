import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import db
import sync
from connectors import ms_sos

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())["d"]


def test_county_code_matches_search_page_order():
    assert ms_sos.county_code("Adams") == 0
    assert ms_sos.county_code("harrison") == 23
    assert ms_sos.county_code("Hinds") == 24
    assert ms_sos.county_code("Jackson") == 29
    assert ms_sos.county_code("Monroe") == 47
    with pytest.raises(ValueError):
        ms_sos.county_code("Atlantis")


def test_parse_search_response():
    parcels, total = ms_sos.parse_search_response(fixture("sos_search_jackson.json"), "Jackson")
    assert total == 167
    assert len(parcels) == 3
    p = parcels[1]
    assert p["source_id"] == "808740"
    assert p["county"] == "Jackson"
    assert p["market_value"] == 910.0
    assert p["address"] == "DAILY RD."
    assert p["city"] == "GAUTIER"
    assert p["zip"] == "39553"
    assert p["parcel_number"] == "85700185.000"
    assert p["ppin"] == "70420"
    assert (p["sec"], p["twp"], p["rng"]) == ("12", "7S", "7W")
    assert p["owners"] == "RICHARD D & MARY N  TOWNSEND"


def test_parse_detail_response():
    d = ms_sos.parse_detail_response(fixture("sos_detail_722310.json"))
    assert d["tax_sale_date"] == "1997-08-25"
    assert d["tax_year"] == 1996
    assert d["legal_description"].startswith("BEG 880 FT E")


def make_client(pages, detail):
    """SOSClient backed by canned responses instead of the live site."""
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("ProcessSearch"):
            return httpx.Response(200, json={"d": pages[body["startingNumber"]]})
        return httpx.Response(200, json={"d": detail})

    client = ms_sos.SOSClient(httpx.Client(transport=httpx.MockTransport(handler)), delay=0)
    return client, calls


def rows(*ids):
    return "^".join(f"{i}%30%Jackson%100.00%0%%%%%%legal%1 Main St%%Pascagoula%MS%39567%P{i}%%Owner" for i in ids)


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    yield c
    c.close()


def test_sync_pages_upserts_and_deactivates(conn):
    detail = fixture("sos_detail_722310.json")
    client, calls = make_client({0: rows("1", "2") + "|3~C~C~0", 1: rows("3") + "|3~C~C~1"}, detail)

    stats = sync.sync_ms_sos(["Jackson"], client=client, conn=conn)
    assert stats["Jackson"] == {"listed": 3, "new": 3, "removed": 0}
    assert calls.count("ProcessSearchDetail") == 3
    assert conn.execute("SELECT tax_year FROM parcels WHERE source_id='1'").fetchone()[0] == 1996

    # Next run: parcel 2 is gone (sold), parcel 4 is new.
    client, calls = make_client({0: rows("1", "3", "4") + "|3~C~C~0"}, detail)
    stats = sync.sync_ms_sos(["Jackson"], client=client, conn=conn)
    assert stats["Jackson"] == {"listed": 3, "new": 1, "removed": 1}
    assert calls.count("ProcessSearchDetail") == 1
    active = {r[0]: r[1] for r in conn.execute("SELECT source_id, active FROM parcels")}
    assert active == {"1": 1, "2": 0, "3": 1, "4": 1}
    # Detail fields from the first run survive a listing-only update.
    assert conn.execute("SELECT tax_year FROM parcels WHERE source_id='1'").fetchone()[0] == 1996


def test_empty_listing_does_not_wipe_county(conn):
    client, _ = make_client({0: rows("1") + "|1~C~C~0"}, "")
    sync.sync_ms_sos(["Jackson"], details=False, client=client, conn=conn)
    client, _ = make_client({0: "|0~C~C~0"}, "")
    stats = sync.sync_ms_sos(["Jackson"], details=False, client=client, conn=conn)
    assert stats["Jackson"]["removed"] == 0
    assert conn.execute("SELECT active FROM parcels").fetchone()[0] == 1


def test_parcels_endpoint(tmp_path, monkeypatch):
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("DATABASE_PATH", path)
    conn = db.connect(path)
    client, _ = make_client({0: rows("1", "2") + "|2~C~C~0"}, "")
    sync.sync_ms_sos(["Jackson"], details=False, client=client, conn=conn)
    conn.close()

    from main import app

    api = TestClient(app)
    body = api.get("/parcels", params={"county": "jackson"}).json()
    assert body["total"] == 2
    assert body["results"][0]["county"] == "Jackson"
    assert api.get("/parcels", params={"county": "Hinds"}).json()["total"] == 0
