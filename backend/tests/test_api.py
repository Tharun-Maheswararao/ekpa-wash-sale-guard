"""End-to-end through HTTP: upload -> pre-sale check -> record sale -> rebuy lock -> summary."""
import pytest
from fastapi.testclient import TestClient

from washguard.api import app
from washguard.portfolio import SAMPLE_DIR


@pytest.fixture
def client():
    c = TestClient(app)
    c.post("/api/reset")
    yield c
    c.post("/api/reset")


def test_state_has_two_sample_accounts(client):
    s = client.get("/api/state").json()
    assert [a["id"] for a in s["accounts"]] == ["TAX-4821", "IRA-7730"]
    assert s["as_of"] == "2026-11-11"


def test_full_demo_flow(client):
    check = client.post("/api/presale-check", json={"account_id": "TAX-4821", "ticker": "NVDA"}).json()
    assert check["disallowed_permanent"] == 625.0

    sold = client.post("/api/trades", json={"account_id": "TAX-4821", "ticker": "NVDA", "action": "SELL",
                                            "quantity": 60, "price": 160})
    assert sold.status_code == 200

    locks = {x["ticker"]: x for x in client.get("/api/rebuy-lock").json()}
    assert locks["NVDA"]["safe_date"] == "2026-12-12"
    assert locks["NVDA"]["at_risk"] == 875.0   # $1,500 loss minus the $625 already lost to the IRA buy

    s = client.get("/api/summary", params={"year": 2026}).json()
    assert s["disallowed_permanent"] == pytest.approx(1003.96 + 625.0)


def test_upload_adds_an_account_from_a_broker_file(client):
    text = (SAMPLE_DIR / "rollover_ira_fidelity.csv").read_bytes()
    r = client.post("/api/upload", files={"file": ("roth.csv", text, "text/csv")},
                    data={"account_name": "Roth IRA", "account_type": "roth_ira", "drip_tickers": "KO, PFE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "fidelity" and body["imported"] == 14
    assert body["account"]["drip_tickers"] == ["KO", "PFE"]
    assert len(client.get("/api/state").json()["accounts"]) == 3


def test_errors_are_400s_with_a_message(client):
    r = client.post("/api/presale-check", json={"account_id": "TAX-4821", "ticker": "TSLA"})
    assert r.status_code == 400 and "holds no TSLA" in r.json()["detail"]
    r = client.post("/api/trades", json={"account_id": "TAX-4821", "ticker": "TSLA", "action": "SELL",
                                         "quantity": 5, "price": 100})
    assert r.status_code == 400 and "only 0 shares" in r.json()["detail"]
