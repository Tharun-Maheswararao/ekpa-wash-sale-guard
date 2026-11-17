"""Feature behavior on the made-up two-account sample portfolio (as of 2026-11-11)."""
from datetime import date
from decimal import Decimal

import pytest

from washguard import features as f
from washguard.portfolio import load_sample

AS_OF = date(2026, 11, 11)


@pytest.fixture
def p():
    return load_sample()


def test_presale_flags_recent_ira_purchase_as_permanent(p):
    r = f.presale_check(p, "TAX-4821", "NVDA", AS_OF)
    assert r["gain_loss"] == -1500.00          # 60 x ($160 - $185)
    assert r["disallowed_permanent"] == 625.00  # 25 IRA shares x $25
    assert r["allowed_gain_loss"] == -875.00
    assert r["rebuy_safe_date"] == "2026-12-12"
    [buy] = r["recent_purchases"]
    assert buy["account"]["id"] == "IRA-7730" and buy["effect"] == "permanent"


def test_presale_partial_quantity_and_custom_price(p):
    r = f.presale_check(p, "TAX-4821", "NVDA", AS_OF, price=Decimal("150"), quantity=Decimal("20"))
    assert r["gain_loss"] == -700.00   # 20 x ($150 - $185)
    assert r["disallowed"] == 700.00   # all 20 shares matched by the 25 IRA shares


def test_presale_gain_needs_no_warning(p):
    r = f.presale_check(p, "TAX-4821", "VTI", AS_OF)
    assert r["is_loss"] is False and r["disallowed"] == 0 and r["rebuy_safe_date"] is None


def test_presale_warns_about_upcoming_dividend_reinvestment(p):
    r = f.presale_check(p, "TAX-4821", "AAPL", AS_OF)
    [risk] = r["drip_risks"]
    assert risk["account"]["id"] == "IRA-7730" and risk["pay_date"] == "2026-11-13" and risk["permanent"]


def test_presale_rejects_overselling(p):
    with pytest.raises(f.FeatureError):
        f.presale_check(p, "TAX-4821", "NVDA", AS_OF, quantity=Decimal("61"))


def test_rebuy_lock_lists_every_recent_loss_with_safe_date(p):
    locks = {x["ticker"]: x for x in f.rebuy_lock(p, AS_OF)}
    assert set(locks) == {"KO", "AMZN", "PFE"}
    assert locks["KO"]["safe_date"] == "2026-11-15"   # Oct 15 + 31 days
    assert locks["PFE"]["safe_date"] == "2026-12-06"
    assert locks["PFE"]["at_risk"] == 600.00
    ira = next(a for a in locks["PFE"]["accounts"] if a["id"] == "IRA-7730")
    assert ira["permanent_if_bought"] and ira["drip_on"]
    # A day after the safe date the lock is gone
    assert "KO" not in {x["ticker"] for x in f.rebuy_lock(p, date(2026, 11, 15))}


def test_drip_alert_high_when_reinvestment_hits_open_window(p):
    alerts = f.drip_alerts(p, AS_OF)
    high = [a for a in alerts if a["severity"] == "high"]
    assert [(a["ticker"], a["account"]["id"]) for a in high] == [("PFE", "IRA-7730")]
    assert high[0]["turn_off_until"] == "2026-12-06" and high[0]["permanent"]
    assert {a["ticker"] for a in alerts if a["severity"] == "medium"} == {"AAPL"}


def test_summary_totals_disallowed_losses_for_the_year(p):
    s = f.summary(p, 2026, AS_OF)
    assert s["total_losses"] == 5826.20
    assert s["disallowed_permanent"] == 1003.96  # MSFT $1,000 + KO DRIP $3.54 + AAPL DRIP $0.42
    assert s["disallowed_deferred"] == 1249.58
    assert s["disallowed"] == 2253.54
    assert s["wash_sale_count"] == 3
    ira = next(a for a in s["by_account"] if a["id"] == "IRA-7730")
    assert ira["caused_by_purchases_here"] == 1003.96
