"""Converter for a Fidelity-style account history CSV.

Layout (modeled on Fidelity's "Activity & Orders" download; verify against a current real export):

    <two blank lines>
    Run Date,Action,Symbol,Description,Type,Quantity,Price ($),Commission ($),Fees ($),Accrued Interest ($),Amount ($),Settlement Date
    10/28/2026, YOU BOUGHT NVIDIA CORPORATION (NVDA) (Cash), NVDA,NVIDIA CORPORATION,Cash,25,170,,,,-4250,10/29/2026
    10/01/2026, REINVESTMENT COCA-COLA CO (KO) (Cash), KO,COCA-COLA CO,Cash,0.3937,65.72,,,,-25.87,
    ...
    <blank line>
    "The data and information in this spreadsheet is provided to you solely for your use ..."  <- footer

Rows are newest first. Sells have negative quantity. Action and symbol cells often have a leading space.
"""
from __future__ import annotations

import csv
import io

from washguard.models import Action, Transaction

from .base import OUT_OF_SCOPE, ConversionResult, chronological, looks_like_option, parse_money, parse_us_date

FORMAT_ID = "fidelity"
LABEL = "Fidelity-style history CSV"
REQUIRED = ["Run Date", "Action", "Symbol", "Quantity", "Price ($)"]

PREFIXES = [
    ("YOU BOUGHT", Action.BUY),
    ("YOU SOLD", Action.SELL),
    ("REINVESTMENT", Action.REINVEST),
]
CASH_PREFIXES = (
    "DIVIDEND RECEIVED", "INTEREST EARNED", "ELECTRONIC FUNDS TRANSFER", "TRANSFERRED FROM",
    "CONTRIBUTION", "ROLLOVER CASH", "FEE CHARGED", "LONG-TERM CAP GAIN", "SHORT-TERM CAP GAIN",
    "TRANSFER OF ASSETS", "DIRECT DEPOSIT", "CASH CONTRIBUTION",
)


def sniff(text: str) -> bool:
    return "Run Date" in text[:2000] and "Price ($)" in text[:2000]


def parse(text: str, account_id: str) -> ConversionResult:
    result = ConversionResult()
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    try:
        start = next(i for i, row in enumerate(rows) if row and row[0].strip() == "Run Date")
    except StopIteration:
        raise ValueError("No Fidelity-style header row (Run Date,Action,...) found") from None
    header = [h.strip() for h in rows[start]]
    missing = [h for h in REQUIRED if h not in header]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    col = {name: header.index(name) for name in header}

    found: list[Transaction] = []
    for n, row in enumerate(rows[start + 1:], start=start + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        raw_line = ",".join(row)
        try:
            trade_date = parse_us_date(row[col["Run Date"]])
        except ValueError:
            # Footer disclaimer text, not a transaction.
            continue
        action_text = row[col["Action"]].strip().upper()
        if action_text.startswith(CASH_PREFIXES):
            result.skip(n, "cash entry", raw_line)
            continue
        if any(word in action_text.lower() for word in OUT_OF_SCOPE):
            result.skip(n, "out of scope for v1", raw_line)
            continue
        action = next((a for prefix, a in PREFIXES if action_text.startswith(prefix)), None)
        if action is None:
            result.skip(n, "unrecognized action", raw_line)
            continue
        symbol = row[col["Symbol"]].strip().upper()
        if not symbol or looks_like_option(symbol):
            result.skip(n, "options and blank symbols are out of scope for v1", raw_line)
            continue
        fees = sum(
            (abs(parse_money(row[col[name]])) for name in ("Commission ($)", "Fees ($)") if name in col),
            start=parse_money(""),
        )
        try:
            found.append(Transaction(
                account_id=account_id,
                date=trade_date,
                action=action,
                ticker=symbol,
                quantity=abs(parse_money(row[col["Quantity"]])),
                price=parse_money(row[col["Price ($)"]]),
                fees=fees,
                source=f"{FORMAT_ID} row {n}",
            ))
        except ValueError as exc:
            result.skip(n, f"could not read row: {exc}", raw_line)
    result.transactions = chronological(found)
    return result
