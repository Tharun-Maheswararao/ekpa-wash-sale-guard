"""Converter for a Schwab-style transaction history CSV.

Layout (modeled on Schwab's history export; verify against a current real export before launch):

    "Transactions  for account Individual ...4821 as of 11/11/2026 ..."   <- optional title line
    "Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"
    "03/20/2026 as of 03/19/2026","Buy","AAPL","APPLE INC","50","$210.00","","-$10,500.00"
    ...
    "Transactions Total","","","","","","","$1,234.56"                     <- optional total line

Rows are newest first. Money has $ and commas. Dates can carry "as of" for the trade date.
"""
from __future__ import annotations

import csv
import io
import re

from washguard.models import Action, Transaction

from .base import OUT_OF_SCOPE, ConversionResult, chronological, looks_like_option, parse_money, parse_us_date

FORMAT_ID = "schwab"
LABEL = "Schwab-style history CSV"
HEADER = ["Date", "Action", "Symbol", "Description", "Quantity", "Price", "Fees & Comm", "Amount"]

ACTIONS = {
    "buy": Action.BUY,
    "sell": Action.SELL,
    "reinvest shares": Action.REINVEST,
}
CASH_ONLY = {
    "qualified dividend", "cash dividend", "non-qualified div", "reinvest dividend", "bank interest",
    "moneylink transfer", "journal", "credit interest", "service fee", "wire funds", "special dividend",
}


def sniff(text: str) -> bool:
    return '"Fees & Comm"' in text[:2000] or "Fees & Comm" in text[:2000]


def _trade_date(raw: str):
    # "03/20/2026 as of 03/19/2026" -> the "as of" date is the trade date
    match = re.search(r"as of (\d{2}/\d{2}/\d{4})", raw)
    return parse_us_date(match.group(1) if match else raw.split()[0])


def parse(text: str, account_id: str) -> ConversionResult:
    result = ConversionResult()
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    try:
        start = next(i for i, row in enumerate(rows) if row[:2] == HEADER[:2])
    except StopIteration:
        raise ValueError("No Schwab-style header row (\"Date\",\"Action\",...) found") from None
    header = rows[start]
    col = {name: header.index(name) for name in HEADER if name in header}
    missing = [h for h in ("Date", "Action", "Symbol", "Quantity", "Price") if h not in col]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")

    found: list[Transaction] = []
    for n, row in enumerate(rows[start + 1:], start=start + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        raw_line = ",".join(row)
        first = row[col["Date"]].strip()
        if first.lower().startswith("transactions total"):
            continue
        action_text = row[col["Action"]].strip()
        key = action_text.lower()
        if key in CASH_ONLY:
            result.skip(n, f"cash entry ({action_text})", raw_line)
            continue
        if any(word in key for word in OUT_OF_SCOPE):
            result.skip(n, f"out of scope for v1 ({action_text})", raw_line)
            continue
        if key not in ACTIONS:
            result.skip(n, f"unrecognized action ({action_text})", raw_line)
            continue
        symbol = row[col["Symbol"]].strip().upper()
        if not symbol or looks_like_option(symbol):
            result.skip(n, "options and blank symbols are out of scope for v1", raw_line)
            continue
        try:
            found.append(Transaction(
                account_id=account_id,
                date=_trade_date(first),
                action=ACTIONS[key],
                ticker=symbol,
                quantity=abs(parse_money(row[col["Quantity"]])),
                price=parse_money(row[col["Price"]]),
                fees=abs(parse_money(row[col["Fees & Comm"]])) if "Fees & Comm" in col else parse_money(""),
                source=f"{FORMAT_ID} row {n}",
            ))
        except ValueError as exc:
            result.skip(n, f"could not read row: {exc}", raw_line)
    result.transactions = chronological(found)
    return result
