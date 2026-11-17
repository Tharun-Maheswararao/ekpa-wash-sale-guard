"""Broker converters: each sample export must convert cleanly into the common format."""
from datetime import date
from decimal import Decimal

import pytest

from washguard.converters import common, convert, detect, fidelity, schwab
from washguard.models import Action
from washguard.portfolio import SAMPLE_DIR


def read(name):
    return (SAMPLE_DIR / name).read_text()


def test_detects_each_format():
    assert detect(read("individual_brokerage_schwab.csv")) == "schwab"
    assert detect(read("rollover_ira_fidelity.csv")) == "fidelity"
    assert detect("account_id,date,action,ticker,quantity,price,fees\n") == "common"
    with pytest.raises(ValueError):
        detect("foo,bar\n1,2\n")


def test_schwab_sample_converts_trades_and_skips_cash_and_options():
    result = schwab.parse(read("individual_brokerage_schwab.csv"), "TAX")
    assert len(result.transactions) == 17
    reasons = " ".join(s["reason"] for s in result.skipped)
    assert "out of scope" in reasons  # the Buy to Open put
    assert "cash entry" in reasons
    # Chronological, oldest first
    dates = [t.date for t in result.transactions]
    assert dates == sorted(dates) and dates[0] == date(2025, 8, 4)


def test_schwab_reads_money_fees_and_as_of_dates():
    result = schwab.parse(read("individual_brokerage_schwab.csv"), "TAX")
    amzn_sell = next(t for t in result.transactions if t.ticker == "AMZN" and t.action == Action.SELL)
    assert amzn_sell.fees == Decimal("0.13") and amzn_sell.price == Decimal("215.00")
    vti_drip = [t for t in result.transactions if t.action == Action.REINVEST]
    assert vti_drip[0].date == date(2026, 3, 27)  # "03/30/2026 as of 03/27/2026" -> trade date


def test_fidelity_sample_handles_blank_lines_footer_and_negative_sells():
    result = fidelity.parse(read("rollover_ira_fidelity.csv"), "IRA")
    assert len(result.transactions) == 14
    assert {t.action for t in result.transactions} == {Action.BUY, Action.REINVEST}
    ko = [t for t in result.transactions if t.ticker == "KO" and t.action == Action.REINVEST]
    assert [t.quantity for t in ko] == [Decimal("0.3638"), Decimal("0.3701"), Decimal("0.3937")]


def test_fidelity_sell_quantity_is_made_positive():
    text = ("Run Date,Action,Symbol,Description,Type,Quantity,Price ($),Commission ($),Fees ($),"
            "Accrued Interest ($),Amount ($),Settlement Date\n"
            "05/01/2026, YOU SOLD EXAMPLE CO (XYZ) (Cash), XYZ,EXAMPLE CO,Cash,-10,40,,0.02,,399.98,05/02/2026\n")
    [t] = fidelity.parse(text, "IRA").transactions
    assert t.action == Action.SELL and t.quantity == Decimal(10) and t.fees == Decimal("0.02")


def test_common_format_round_trips():
    _, result = convert(read("individual_brokerage_schwab.csv"), "TAX")
    again = common.parse(common.write(result.transactions))
    assert [(t.date, t.action, t.ticker, t.quantity, t.price) for t in again.transactions] == \
           [(t.date, t.action, t.ticker, t.quantity, t.price) for t in result.transactions]


def test_bad_header_is_a_clear_error():
    with pytest.raises(ValueError, match="header"):
        schwab.parse("hello\nworld\n", "TAX")
