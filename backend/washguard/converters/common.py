"""The common CSV format: one row per trade, the shape every converter writes.

    account_id,date,action,ticker,quantity,price,fees
    TAX-4821,2026-03-20,BUY,AAPL,50,210.00,0
"""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from washguard.models import Action, Transaction

from .base import ConversionResult

FORMAT_ID = "common"
LABEL = "Ekpa common CSV"
COLUMNS = ["account_id", "date", "action", "ticker", "quantity", "price", "fees"]


def sniff(text: str) -> bool:
    return text.lstrip("﻿").split("\n", 1)[0].strip().lower().startswith("account_id,date,action")


def parse(text: str, account_id: str | None = None) -> ConversionResult:
    """Read a common CSV. If account_id is given it overrides the file's column."""
    result = ConversionResult()
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for n, row in enumerate(reader, start=2):
        try:
            result.transactions.append(Transaction(
                account_id=account_id or row["account_id"].strip(),
                date=date.fromisoformat(row["date"].strip()),
                action=Action(row["action"].strip().upper()),
                ticker=row["ticker"].strip().upper(),
                quantity=Decimal(row["quantity"]),
                price=Decimal(row["price"]),
                fees=Decimal(row.get("fees") or "0"),
                source=f"{FORMAT_ID} row {n}",
            ))
        except (KeyError, ValueError, ArithmeticError) as exc:
            result.skip(n, f"could not read row: {exc}", ",".join(str(v) for v in row.values()))
    result.transactions.sort(key=lambda t: t.date)
    return result


def write(transactions: list[Transaction]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for t in transactions:
        writer.writerow([t.account_id, t.date.isoformat(), t.action.value, t.ticker, t.quantity, t.price, t.fees])
    return out.getvalue()
