from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def upload(name, content):
    return client.post("/upload", files={"file": (name, content, "text/csv")})


def test_root():
    assert client.get("/").json() == {"message": "API is running!"}


def test_upload_csv():
    res = upload("liens.csv", b"parcel,amount\nA1,100.5\nB2,200\n")
    assert res.status_code == 200
    body = res.json()
    assert body["row_count"] == 2
    assert body["columns"] == ["parcel", "amount"]
    assert body["preview"][0] == {"parcel": "A1", "amount": 100.5}


def test_upload_with_missing_values():
    res = upload("liens.csv", b"parcel,amount\nA1,\n,200\n")
    assert res.status_code == 200
    assert res.json()["preview"] == [
        {"parcel": "A1", "amount": None},
        {"parcel": None, "amount": 200.0},
    ]


def test_rejects_non_csv():
    assert upload("liens.xlsx", b"whatever").status_code == 400


def test_rejects_empty_csv():
    assert upload("empty.csv", b"").status_code == 400
