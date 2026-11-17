"""The 20 wash sale rule cases, written before the engine.

Each test cites where its expected numbers come from:
  * SPEC      - the four cases in the project brief
  * P550      - IRS Publication 550 (2025), Chapter 4, "Wash Sales"
  * RR 56-602 - Rev. Rul. 56-602 (selling part of a single purchase)
  * DESIGN    - a v1 engine decision, listed in README "Questions for tax review"

None of these are tax advice. Every case still needs sign-off from a tax professional.
"""
from datetime import date

from helpers import ACCOUNTS, SALE_DAY, d, day, money, tx

from washguard.engine import run_engine


def only_sale(result):
    sales = [x for x in result.dispositions]
    assert len(sales) == 1, sales
    return sales[0]


# --- SPEC: the four cases from the brief -------------------------------------------------

def test_01_rebuy_in_other_taxable_account_defers_loss_into_basis():
    """SPEC + P550: $1,000 loss is disallowed and added to the new shares: $42 + $10 = $52."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("B", day(14), "BUY", 100, 42),
    ])
    sale = only_sale(r)
    assert money(sale.gain_loss) == d("-1000.00")
    assert money(sale.disallowed) == d("1000.00")
    assert money(sale.disallowed_permanent) == d("0.00")
    assert money(sale.allowed_gain_loss) == d("0.00")
    [lot] = r.open_lots("B", "XYZ")
    assert lot.basis_per_share == d(52)
    assert money(lot.basis) == d("5200.00")


def test_02_rebuy_in_ira_loses_the_loss_for_good():
    """SPEC + P550 trigger (4): IRA purchase disallows the loss and gives no basis adjustment."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("IRA", day(14), "BUY", 100, 42),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("1000.00")
    assert money(sale.disallowed_permanent) == d("1000.00")
    assert sale.matches[0].permanent is True
    [lot] = r.open_lots("IRA", "XYZ")
    assert lot.basis_per_share == d(42)


def test_03_only_40_shares_rebought_disallows_40_percent():
    """SPEC + P550 "more or less stock bought than sold": 40 of 100 shares -> $400 disallowed."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("B", day(14), "BUY", 40, 42),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("400.00")
    assert money(sale.allowed_gain_loss) == d("-600.00")
    [lot] = r.open_lots("B", "XYZ")
    assert lot.basis_per_share == d(52)


def test_04_window_after_sale_ends_on_day_30():
    """SPEC + P550 "within 30 days ... after": day 30 is a wash, day 31 is not."""
    on_day_30 = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("B", day(30), "BUY", 100, 42),
    ])
    on_day_31 = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("B", day(31), "BUY", 100, 42),
    ])
    assert money(only_sale(on_day_30).disallowed) == d("1000.00")
    assert money(only_sale(on_day_31).disallowed) == d("0.00")
    assert money(only_sale(on_day_31).allowed_gain_loss) == d("-1000.00")
    [lot] = on_day_31.open_lots("B", "XYZ")
    assert lot.basis_per_share == d(42)


# --- P550: window, gains, worked examples -----------------------------------------------

def test_05_window_before_sale_starts_30_days_earlier():
    """P550 "within 30 days before": a buy 30 days before the sale is a wash, 31 days is not."""
    def run(offset):
        return run_engine(ACCOUNTS, [
            tx("A", "2025-06-02", "BUY", 100, 50),
            tx("B", day(offset), "BUY", 100, 45),
            tx("A", day(0), "SELL", 100, 40),
        ])
    assert money(only_sale(run(-30)).disallowed) == d("1000.00")
    assert money(only_sale(run(-31)).disallowed) == d("0.00")


def test_06_sale_at_a_gain_is_never_a_wash_sale():
    """P550: the rule only covers sales "at a loss"."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 30),
        tx("A", day(0), "SELL", 100, 40),
        tx("B", day(5), "BUY", 100, 41),
    ])
    sale = only_sale(r)
    assert money(sale.gain_loss) == d("1000.00")
    assert sale.matches == []
    assert r.open_lots("B", "XYZ")[0].basis_per_share == d(41)


def test_07_pub550_example_basis_becomes_1050():
    """P550 Wash Sales example: buy 100 for $1,000, sell for $750, rebuy 100 for $800 -> basis $1,050."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-01-06", "BUY", 100, 10),
        tx("A", "2025-08-01", "SELL", 100, "7.50"),
        tx("A", "2025-08-20", "BUY", 100, 8),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("250.00")
    assert money(r.open_lots("A", "XYZ")[0].basis) == d("1050.00")


def test_08_pub550_more_bought_before_sale_than_needed():
    """P550 "more or less stock bought" Example 1: 75 replacement shares bought before the sale.

    $750 of the $1,000 loss is disallowed and $250 is deductible. The 50-share lot's basis rises
    by $500 to $3,250 and the 25-share lot's basis rises by $250 to $1,375.
    """
    r = run_engine(ACCOUNTS, [
        tx("A", "2024-09-20", "BUY", 100, 50),      # $5,000
        tx("A", "2024-12-13", "BUY", 50, 55),       # $2,750
        tx("A", "2024-12-20", "BUY", 25, 45),       # $1,125
        tx("A", "2025-01-03", "SELL", 100, 40),     # $4,000 -> $1,000 loss (FIFO: Sept lot)
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("750.00")
    assert money(sale.allowed_gain_loss) == d("-250.00")
    lots = r.open_lots("A", "XYZ")
    assert [money(lot.basis) for lot in lots] == [d("3250.00"), d("1375.00")]


def test_09_pub550_replacements_matched_in_order_bought():
    """P550 Example 2: 50 shares bought on each of 4 days after the sale.

    The full $1,000 loss is disallowed. $500 goes to the Feb 3 lot and $500 to the Feb 4 lot.
    The Feb 5 and Feb 6 lots are not changed.
    """
    r = run_engine(ACCOUNTS, [
        tx("A", "2024-09-16", "BUY", 100, 50),
        tx("A", "2025-01-29", "SELL", 100, 40),
        tx("A", "2025-02-03", "BUY", 50, 41),
        tx("A", "2025-02-04", "BUY", 50, 41),
        tx("A", "2025-02-05", "BUY", 50, 41),
        tx("A", "2025-02-06", "BUY", 50, 41),
    ])
    assert money(only_sale(r).disallowed) == d("1000.00")
    adjustments = [(lot.acquired.isoformat(), money(lot.wash_adjustment)) for lot in r.open_lots("A", "XYZ")]
    assert adjustments == [
        ("2025-02-03", d("500.00")),
        ("2025-02-04", d("500.00")),
        ("2025-02-05", d("0.00")),
        ("2025-02-06", d("0.00")),
    ]


def test_10_pub550_loss_and_gain_on_same_day_are_not_netted():
    """P550 "Loss and gain on same day": a disallowed loss on one block can't offset gains on others.

    300 shares bought at $158, $100 and $95 are sold at $125. 250 shares are rebought within 30 days.
    The $33 per share loss on the $158 block ($3,300) is disallowed. The $2,500 and $3,000 gains stand.
    """
    r = run_engine(ACCOUNTS, [
        tx("A", "2019-03-01", "BUY", 100, 158),
        tx("A", "2019-06-03", "BUY", 100, 100),
        tx("A", "2019-09-03", "BUY", 100, 95),
        tx("A", "2024-12-27", "SELL", 300, 125),
        tx("A", "2025-01-10", "BUY", 250, 126),
    ])
    blocks = sorted(r.dispositions, key=lambda x: x.acquired)
    assert [money(b.gain_loss) for b in blocks] == [d("-3300.00"), d("2500.00"), d("3000.00")]
    assert [money(b.allowed_gain_loss) for b in blocks] == [d("0.00"), d("2500.00"), d("3000.00")]
    lots = r.open_lots("A", "XYZ")
    assert sum(lot.quantity for lot in lots) == d(250)
    adjusted = [lot for lot in lots if lot.wash_adjustment > 0]
    assert len(adjusted) == 1 and adjusted[0].quantity == d(100)
    assert adjusted[0].basis_per_share == d(159)  # $126 + $33


# --- Which shares count as replacements --------------------------------------------------

def test_11_the_shares_sold_are_not_their_own_replacement():
    """P550 definition: the shares you bought and then sold are not "substantially identical stock you buy"."""
    r = run_engine(ACCOUNTS, [
        tx("A", day(-10), "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("0.00")
    assert money(sale.allowed_gain_loss) == d("-1000.00")


def test_12_selling_part_of_one_purchase_is_not_a_wash_sale():
    """RR 56-602: selling 40 of 100 shares bought together. The other 60 are not replacements."""
    r = run_engine(ACCOUNTS, [
        tx("A", day(-10), "BUY", 100, 50),
        tx("A", day(0), "SELL", 40, 40),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("0.00")
    [lot] = r.open_lots("A", "XYZ")
    assert lot.quantity == d(60) and lot.basis_per_share == d(50)


def test_13_one_purchase_cannot_wash_two_losses():
    """P550 "the shares so matched": each replacement share is used once, earliest loss sale first (DESIGN)."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("B", "2025-06-02", "BUY", 100, 60),
        tx("A", day(0), "SELL", 100, 40),   # -$1,000
        tx("B", day(8), "SELL", 100, 40),   # -$2,000
        tx("A", day(14), "BUY", 100, 42),   # inside both windows
    ])
    first, second = sorted(r.dispositions, key=lambda x: x.sale_date)
    assert money(first.disallowed) == d("1000.00")
    assert money(second.disallowed) == d("0.00")
    assert money(second.allowed_gain_loss) == d("-2000.00")


def test_14_different_ticker_is_not_matched_in_v1():
    """Scope: v1 matches the same ticker only. "Substantially identical" funds are out of scope."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50, ticker="VOO"),
        tx("A", day(0), "SELL", 100, 40, ticker="VOO"),
        tx("B", day(5), "BUY", 100, 41, ticker="IVV"),
    ])
    assert money(only_sale(r).disallowed) == d("0.00")


# --- Carry-forward, holding period, FIFO -------------------------------------------------

def test_15_chained_wash_sale_carries_deferred_loss_forward():
    """P550 "postpones the loss deduction until the disposition of the new stock".

    The replacement shares (basis $52) are sold at $41, a $1,100 loss. They are rebought at $43,
    so that loss is also deferred. The new basis is $43 + $11 = $54.
    """
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("A", day(14), "BUY", 100, 42),
        tx("A", day(39), "SELL", 100, 41),
        tx("A", day(49), "BUY", 100, 43),
    ])
    first, second = sorted(r.dispositions, key=lambda x: x.sale_date)
    assert money(first.disallowed) == d("1000.00")
    assert money(second.gain_loss) == d("-1100.00")
    assert money(second.disallowed) == d("1100.00")
    assert r.open_lots("A", "XYZ")[0].basis_per_share == d(54)


def test_16_replacement_holding_period_includes_sold_shares():
    """P550: "Your holding period for the new stock ... includes the holding period of the stock ... sold".

    The old shares were held 416 days (2025-01-10 to 2026-03-02). The replacement bought 2026-03-16
    takes a holding start of 2025-01-24. If it is sold on 2026-03-20, that sale is long term.
    """
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-01-10", "BUY", 100, 50),
        tx("A", "2026-03-02", "SELL", 100, 40),
        tx("B", "2026-03-16", "BUY", 100, 42),
        tx("B", "2026-03-20", "SELL", 100, 60),
    ])
    replacement_sale = [x for x in r.dispositions if x.account_id == "B"][0]
    assert replacement_sale.holding_start == date(2025, 1, 24)
    assert replacement_sale.term == "long"
    # Deferred $1,000 comes back on the replacement sale: (60 - 52) * 100
    assert money(replacement_sale.gain_loss) == d("800.00")


def test_17_fifo_sells_the_oldest_lot_first():
    """SPEC: first in, first out. Selling 100 of 200 shares uses the older $30 lot, which is a gain."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-01-06", "BUY", 100, 30),
        tx("A", "2025-06-02", "BUY", 100, 60),
        tx("A", day(0), "SELL", 100, 45),
    ])
    sale = only_sale(r)
    assert sale.acquired == date(2025, 1, 6)
    assert money(sale.gain_loss) == d("1500.00")
    [lot] = r.open_lots("A", "XYZ")
    assert lot.basis_per_share == d(60)


# --- Dividend reinvestment and IRA sales -------------------------------------------------

def test_18_dividend_reinvestment_triggers_a_partial_wash():
    """SPEC (DRIP flags) + P550 "buy substantially identical stock": 0.5 reinvested shares disallow $5."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("A", day(0), "SELL", 100, 40),
        tx("B", day(8), "REINVEST", "0.5", 41),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed) == d("5.00")
    assert money(sale.allowed_gain_loss) == d("-995.00")
    assert r.open_lots("B", "XYZ")[0].basis_per_share == d(51)


def test_19_reinvestment_inside_roth_ira_is_permanent():
    """P550 trigger (4) covers Roth IRAs too. 2.5 reinvested shares lose $25 for good."""
    r = run_engine(ACCOUNTS, [
        tx("A", "2025-06-02", "BUY", 100, 50),
        tx("ROTH", day(-12), "REINVEST", "2.5", 44),
        tx("A", day(0), "SELL", 100, 40),
    ])
    sale = only_sale(r)
    assert money(sale.disallowed_permanent) == d("25.00")
    assert money(sale.allowed_gain_loss) == d("-975.00")
    assert r.open_lots("ROTH", "XYZ")[0].basis_per_share == d(44)


def test_20_sales_inside_an_ira_are_not_wash_sales():
    """P550 applies to deductible losses. A sale inside an IRA has no deductible loss to disallow (DESIGN)."""
    r = run_engine(ACCOUNTS, [
        tx("IRA", "2025-06-02", "BUY", 100, 50),
        tx("IRA", day(0), "SELL", 100, 40),
        tx("A", day(5), "BUY", 100, 42),
    ])
    sale = only_sale(r)
    assert sale.tax_reportable is False
    assert sale.matches == []
    assert r.open_lots("A", "XYZ")[0].basis_per_share == d(42)
