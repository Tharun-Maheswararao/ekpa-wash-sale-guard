"""The four user-facing features, built on the engine. Every function returns plain JSON-ready dicts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .engine import WINDOW_DAYS, ZERO, Disposition, EngineResult, run_engine
from .models import AccountType, Action, Transaction
from .portfolio import Portfolio

SAFE_AFTER_DAYS = WINDOW_DAYS + 1  # day 31 after the last loss sale is the first safe day


class FeatureError(ValueError):
    pass


def money(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.01")))


def shares(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.0001")))


def short_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _unmatched_loss(pieces: list[Disposition]) -> tuple[Decimal, Decimal]:
    """Shares and dollars of loss that a new purchase could still disallow."""
    qty = dollars = ZERO
    for p in pieces:
        if p.tax_reportable and p.is_loss:
            free = p.quantity - p.matched_shares
            qty += free
            dollars += free * p.loss_per_share
    return qty, dollars


def _account_dict(portfolio: Portfolio, account_id: str) -> dict:
    a = portfolio.account(account_id)
    return {"id": a.id, "name": a.name, "type": a.type.value, "type_label": a.type.label}


# --- Holdings ------------------------------------------------------------------------------

def holdings(portfolio: Portfolio, as_of: date) -> list[dict]:
    result = portfolio.run(as_of)
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for lot in result.open_lots():
        grouped[(lot.account_id, lot.ticker)].append(lot)
    rows = []
    for (account_id, ticker), lots in sorted(grouped.items()):
        qty = sum((l.quantity for l in lots), ZERO)
        basis = sum((l.basis for l in lots), ZERO)
        adj = sum((l.wash_adjustment for l in lots), ZERO)
        price = portfolio.price(ticker)
        value = qty * price if price is not None else None
        rows.append({
            "account": _account_dict(portfolio, account_id),
            "ticker": ticker,
            "shares": shares(qty),
            "basis": money(basis),
            "basis_per_share": money(basis / qty),
            "wash_adjustment": money(adj),
            "price": money(price) if price is not None else None,
            "market_value": money(value) if value is not None else None,
            "unrealized": money(value - basis) if value is not None else None,
            "drip_on": ticker in portfolio.account(account_id).drip_tickers,
            "lots": [{
                "lot_id": l.lot_id,
                "acquired": l.acquired.isoformat(),
                "holding_start": l.holding_start.isoformat(),
                "action": l.action.value,
                "shares": shares(l.quantity),
                "basis_per_share": money(l.basis_per_share),
                "wash_adjustment_per_share": money(l.adjustment_per_share),
                "used_as_replacement": l.used_as_replacement,
            } for l in lots],
        })
    return rows


# --- Pre-sale check -----------------------------------------------------------------------

def presale_check(portfolio: Portfolio, account_id: str, ticker: str, sale_date: date,
                  price: Decimal | None = None, quantity: Decimal | None = None) -> dict:
    ticker = ticker.upper()
    account = portfolio.account(account_id)
    history = portfolio.history(sale_date)
    base = run_engine(portfolio.accounts, history)
    held = sum((l.quantity for l in base.open_lots(account_id, ticker)), ZERO)
    if held == 0:
        raise FeatureError(f"{account.name} holds no {ticker} on {sale_date}")
    qty = held if quantity is None else quantity
    if qty <= 0 or qty > held:
        raise FeatureError(f"Quantity must be between 0 and {shares(held)}")
    price = price if price is not None else portfolio.price(ticker)
    if price is None:
        raise FeatureError(f"No price on file for {ticker}; enter one")

    hypothetical = Transaction(account_id, sale_date, Action.SELL, ticker, qty, price, source="pre-sale check")
    sim = run_engine(portfolio.accounts, history + [hypothetical])
    pieces = sim.dispositions_for(len(history))
    gain_loss = sum((p.gain_loss for p in pieces), ZERO)
    disallowed = sum((p.disallowed for p in pieces), ZERO)
    permanent = sum((p.disallowed_permanent for p in pieces), ZERO)
    is_loss = gain_loss < 0
    taxable = account.type == AccountType.TAXABLE

    # Purchases in the 30 days before the sale, across all accounts, and what each does to this sale.
    matched_by_tx: dict[int, list] = defaultdict(list)
    for p in pieces:
        for m in p.matches:
            matched_by_tx[m.tx_index].append(m)
    sold_from = {p.lot_tx_index for p in pieces}
    used_earlier = {l.tx_index for l in base.lots if l.used_as_replacement}
    window_start = sale_date - timedelta(days=WINDOW_DAYS)
    purchases = []
    for i, t in enumerate(history):
        if t.ticker != ticker or not t.action.is_acquisition or not (window_start <= t.date <= sale_date):
            continue
        matches = matched_by_tx.get(i, [])
        hit = sum((m.shares for m in matches), ZERO)
        if hit > 0:
            effect = "permanent" if matches[0].permanent else "deferred"
        elif i in sold_from:
            effect = "being_sold"
        elif not taxable or not is_loss:
            effect = "no_effect"
        elif i in used_earlier:
            effect = "used_earlier"
        else:
            effect = "no_effect"
        purchases.append({
            "date": t.date.isoformat(),
            "days_before_sale": (sale_date - t.date).days,
            "account": _account_dict(portfolio, t.account_id),
            "action": t.action.value,
            "shares": shares(t.quantity),
            "price": money(t.price),
            "matched_shares": shares(hit),
            "disallowed": money(sum((m.disallowed for m in matches), ZERO)),
            "effect": effect,
        })

    # Scheduled dividend reinvestment that would land inside the 30 days after the sale.
    free_qty, free_dollars = _unmatched_loss(pieces)
    free_lps = free_dollars / free_qty if free_qty else ZERO
    drip_risks = []
    if taxable and is_loss:
        safe = sale_date + timedelta(days=SAFE_AFTER_DAYS)
        for a in portfolio.accounts:
            if ticker not in a.drip_tickers:
                continue
            held_after = sum((l.quantity for l in sim.open_lots(a.id, ticker)), ZERO)
            div = portfolio.next_dividend(ticker, after=sale_date, until=sale_date + timedelta(days=WINDOW_DAYS))
            if held_after == 0:
                continue
            est = held_after * div.amount_per_share / price if div else None
            at_risk = min(est, free_qty) * free_lps if est is not None else None
            drip_risks.append({
                "account": _account_dict(portfolio, a.id),
                "pay_date": div.pay_date.isoformat() if div else None,
                "estimated_shares": shares(est) if est is not None else None,
                "estimated_disallowed": money(at_risk) if at_risk is not None else None,
                "permanent": a.type.is_retirement,
                "turn_off_until": safe.isoformat(),
            })

    messages = []
    if not taxable:
        messages.append({"level": "info", "text": f"{account.name} is a {account.type.label}. Wash sale rules "
                         "don't change anything for sales inside it."})
    elif not is_loss:
        messages.append({"level": "ok", "text": "This sale is a gain, so the wash sale rule doesn't apply."})
    elif disallowed == 0 and not drip_risks:
        messages.append({"level": "ok", "text": f"No purchases of {ticker} in the last 30 days. The full loss counts "
                         f"if you don't buy {ticker} in any account before "
                         f"{short_date(sale_date + timedelta(days=SAFE_AFTER_DAYS))}."})
    if permanent > 0:
        messages.append({"level": "danger", "text": f"${money(permanent):,.2f} of this loss would be lost for good "
                         "because of a recent purchase in a retirement account."})
    if disallowed - permanent > 0:
        messages.append({"level": "warn", "text": f"${money(disallowed - permanent):,.2f} would be deferred "
                         "into the basis of shares bought in a taxable account."})
    for r in drip_risks:
        when = short_date(date.fromisoformat(r["pay_date"])) if r["pay_date"] else "inside the window"
        messages.append({"level": "danger" if r["permanent"] else "warn",
                         "text": f"Dividend reinvestment is on for {ticker} in {r['account']['name']} "
                                 f"({when}). Switch it to cash until "
                                 f"{short_date(date.fromisoformat(r['turn_off_until']))}."})

    return {
        "account": _account_dict(portfolio, account_id),
        "ticker": ticker,
        "sale_date": sale_date.isoformat(),
        "quantity": shares(qty),
        "held": shares(held),
        "price": money(price),
        "proceeds": money(sum((p.proceeds for p in pieces), ZERO)),
        "cost_basis": money(sum((p.cost_basis for p in pieces), ZERO)),
        "gain_loss": money(gain_loss),
        "is_loss": is_loss,
        "tax_reportable": taxable,
        "disallowed": money(disallowed),
        "disallowed_permanent": money(permanent),
        "disallowed_deferred": money(disallowed - permanent),
        "allowed_gain_loss": money(gain_loss + disallowed),
        "lots": [{
            "acquired": p.acquired.isoformat(),
            "shares": shares(p.quantity),
            "cost_basis": money(p.cost_basis),
            "gain_loss": money(p.gain_loss),
            "term": p.term,
            "disallowed": money(p.disallowed),
        } for p in pieces],
        "recent_purchases": purchases,
        "drip_risks": drip_risks,
        "rebuy_safe_date": (sale_date + timedelta(days=SAFE_AFTER_DAYS)).isoformat() if taxable and is_loss else None,
        "messages": messages,
    }


# --- Rebuy lock -----------------------------------------------------------------------------

def _recent_loss_pieces(result: EngineResult, as_of: date) -> dict[str, list[Disposition]]:
    start = as_of - timedelta(days=WINDOW_DAYS)
    by_ticker: dict[str, list[Disposition]] = defaultdict(list)
    for p in result.dispositions:
        if p.tax_reportable and p.is_loss and start <= p.sale_date <= as_of:
            by_ticker[p.ticker].append(p)
    return by_ticker


def rebuy_lock(portfolio: Portfolio, as_of: date) -> list[dict]:
    result = portfolio.run(as_of)
    locks = []
    for ticker, pieces in sorted(_recent_loss_pieces(result, as_of).items()):
        free_qty, free_dollars = _unmatched_loss(pieces)
        safe = max(p.sale_date for p in pieces) + timedelta(days=SAFE_AFTER_DAYS)
        sales = defaultdict(list)
        for p in pieces:
            sales[p.tx_index].append(p)
        sale_rows = []
        for group in sales.values():
            q, d = _unmatched_loss(group)
            first = group[0]
            sale_rows.append({
                "date": first.sale_date.isoformat(),
                "account": _account_dict(portfolio, first.account_id),
                "shares": shares(sum((p.quantity for p in group), ZERO)),
                "loss": money(-sum((p.gain_loss for p in group), ZERO)),
                "already_disallowed": money(sum((p.disallowed for p in group), ZERO)),
                "still_at_risk": money(d),
                "safe_date": (first.sale_date + timedelta(days=SAFE_AFTER_DAYS)).isoformat(),
            })
        sale_rows.sort(key=lambda r: r["date"])
        held_by = {l.account_id for l in result.open_lots(ticker=ticker)}
        locks.append({
            "ticker": ticker,
            "safe_date": safe.isoformat(),
            "days_left": (safe - as_of).days,
            "at_risk": money(free_dollars),
            "at_risk_shares": shares(free_qty),
            "sales": sale_rows,
            "accounts": [{
                **_account_dict(portfolio, a.id),
                "permanent_if_bought": a.type.is_retirement,
                "drip_on": ticker in a.drip_tickers,
                "holds": a.id in held_by,
            } for a in portfolio.accounts],
        })
    return sorted(locks, key=lambda x: x["safe_date"])


# --- Dividend reinvestment alerts -------------------------------------------------------------

def drip_alerts(portfolio: Portfolio, as_of: date) -> list[dict]:
    result = portfolio.run(as_of)
    recent = _recent_loss_pieces(result, as_of)
    alerts = []
    for a in portfolio.accounts:
        for ticker in sorted(a.drip_tickers):
            held = sum((l.quantity for l in result.open_lots(a.id, ticker)), ZERO)
            price = portfolio.price(ticker)
            div = portfolio.next_dividend(ticker, after=as_of)
            est = held * div.amount_per_share / price if div and price and held else None
            base = {
                "account": _account_dict(portfolio, a.id),
                "ticker": ticker,
                "held": shares(held),
                "pay_date": div.pay_date.isoformat() if div else None,
                "estimated_shares": shares(est) if est is not None else None,
                "permanent": a.type.is_retirement,
            }
            pieces = recent.get(ticker, [])
            free_qty, free_dollars = _unmatched_loss(pieces)
            if pieces and free_qty > 0 and held > 0:
                safe = max(p.sale_date for p in pieces) + timedelta(days=SAFE_AFTER_DAYS)
                if div is None or div.pay_date < safe:
                    risk = min(est, free_qty) * free_dollars / free_qty if est is not None else None
                    last = max(p.sale_date for p in pieces)
                    alerts.append({**base, "severity": "high", "turn_off_until": safe.isoformat(),
                        "estimated_disallowed": money(risk) if risk is not None else None,
                        "title": f"{ticker} reinvestment lands inside a wash sale window",
                        "text": (f"You sold {ticker} at a loss on {short_date(last)}. "
                                 + (f"The {short_date(div.pay_date)} dividend will buy about {shares(est)} shares "
                                    if div else "Any dividend will buy shares ")
                                 + f"in {a.name} before the {short_date(safe)} safe date. "
                                 + ("That part of the loss would be lost for good." if a.type.is_retirement
                                    else "That part of the loss would be deferred.")),
                        "action": f"Switch {ticker} dividends to cash in {a.name} until {short_date(safe)}."})
                    continue
            # Watch: a taxable position at an unrealized loss that a sale might realize.
            losing = [l for l in result.open_lots(ticker=ticker)
                      if price is not None and result.accounts[l.account_id].type == AccountType.TAXABLE
                      and l.basis_per_share > price]
            loss_qty = sum((l.quantity for l in losing), ZERO)
            if losing and div and div.pay_date <= as_of + timedelta(days=WINDOW_DAYS) and held > 0:
                loss = sum((l.quantity * (l.basis_per_share - price) for l in losing), ZERO)
                risk = min(est, loss_qty) * loss / loss_qty
                after = div.pay_date + timedelta(days=SAFE_AFTER_DAYS)
                where = ", ".join(sorted({portfolio.account(l.account_id).name for l in losing}))
                alerts.append({**base, "severity": "medium", "turn_off_until": None,
                    "estimated_disallowed": money(risk),
                    "title": f"{ticker} reinvestment could wash a sale you haven't made yet",
                    "text": (f"You hold {ticker} at a ${money(loss):,.2f} loss in {where}. If you sell it before "
                             f"{short_date(after)}, the {short_date(div.pay_date)} reinvestment in {a.name} "
                             "would disallow part of that loss."),
                    "action": f"If you plan to sell {ticker}, switch dividends to cash in {a.name} first."})
                continue
            if pieces and div:
                safe = max(p.sale_date for p in pieces) + timedelta(days=SAFE_AFTER_DAYS)
                text = (f"The next {ticker} dividend ({short_date(div.pay_date)}) is paid after the "
                        f"{short_date(safe)} safe date for your recent {ticker} loss sale.")
            elif held == 0:
                text = f"{a.name} holds no {ticker}, so nothing will be reinvested."
            else:
                text = f"No recent {ticker} loss sale and no losing {ticker} position nearby."
            alerts.append({**base, "severity": "ok", "turn_off_until": None, "estimated_disallowed": 0.0,
                           "title": f"{ticker} reinvestment is clear", "text": text, "action": None})
    order = {"high": 0, "medium": 1, "ok": 2}
    return sorted(alerts, key=lambda x: (order[x["severity"]], x["ticker"]))


# --- Summary --------------------------------------------------------------------------------

def summary(portfolio: Portfolio, year: int, as_of: date) -> dict:
    result = portfolio.run(as_of)
    pieces = [p for p in result.dispositions if p.tax_reportable and p.sale_date.year == year]

    def total(items, attr):
        return sum((getattr(p, attr) for p in items), ZERO)

    losses = [p for p in pieces if p.is_loss]
    by_account = defaultdict(lambda: defaultdict(lambda: ZERO))
    by_ticker = defaultdict(lambda: defaultdict(lambda: ZERO))
    by_replacement = defaultdict(lambda: ZERO)
    for p in losses:
        for bucket in (by_account[p.account_id], by_ticker[p.ticker]):
            bucket["loss"] += -p.gain_loss
            bucket["disallowed"] += p.disallowed
            bucket["permanent"] += p.disallowed_permanent
        for m in p.matches:
            by_replacement[m.account_id] += m.disallowed

    sales = defaultdict(list)
    for p in losses:
        sales[p.tx_index].append(p)
    events = []
    for group in sales.values():
        first = group[0]
        reps = defaultdict(lambda: {"shares": ZERO, "disallowed": ZERO})
        for p in group:
            for m in p.matches:
                r = reps[m.tx_index]
                r["shares"] += m.shares
                r["disallowed"] += m.disallowed
                r["match"] = m
        events.append({
            "date": first.sale_date.isoformat(),
            "ticker": first.ticker,
            "account": _account_dict(portfolio, first.account_id),
            "shares": shares(total(group, "quantity")),
            "loss": money(-total(group, "gain_loss")),
            "disallowed": money(total(group, "disallowed")),
            "permanent": money(total(group, "disallowed_permanent")),
            "deferred": money(total(group, "disallowed_deferred")),
            "allowed_loss": money(-total(group, "allowed_gain_loss")),
            "replacements": [{
                "date": r["match"].acquired.isoformat(),
                "account": _account_dict(portfolio, r["match"].account_id),
                "action": r["match"].action.value,
                "shares": shares(r["shares"]),
                "disallowed": money(r["disallowed"]),
                "permanent": r["match"].permanent,
            } for r in sorted(reps.values(), key=lambda r: r["match"].acquired)],
        })
    events.sort(key=lambda e: e["date"])

    return {
        "year": year,
        "as_of": as_of.isoformat(),
        "realized_gain_loss": money(total(pieces, "gain_loss")),
        "total_losses": money(-total(losses, "gain_loss")),
        "total_gains": money(total([p for p in pieces if not p.is_loss], "gain_loss")),
        "disallowed": money(total(losses, "disallowed")),
        "disallowed_deferred": money(total(losses, "disallowed_deferred")),
        "disallowed_permanent": money(total(losses, "disallowed_permanent")),
        "allowed_gain_loss": money(total(pieces, "allowed_gain_loss")),
        "wash_sale_count": sum(1 for e in events if e["disallowed"] > 0),
        "by_account": [{**_account_dict(portfolio, k), **{x: money(v[x]) for x in ("loss", "disallowed", "permanent")},
                        "caused_by_purchases_here": money(by_replacement.get(k, ZERO))}
                       for k, v in sorted(by_account.items())]
                      + [{**_account_dict(portfolio, k), "loss": 0.0, "disallowed": 0.0, "permanent": 0.0,
                          "caused_by_purchases_here": money(v)}
                         for k, v in sorted(by_replacement.items()) if k not in by_account],
        "by_ticker": [{"ticker": k, **{x: money(v[x]) for x in ("loss", "disallowed", "permanent")}}
                      for k, v in sorted(by_ticker.items())],
        "events": events,
    }
