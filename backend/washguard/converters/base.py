"""Shared helpers for broker converters."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from washguard.models import Transaction

# Actions v1 deliberately leaves out. Rows with these are reported as skipped, not dropped silently.
OUT_OF_SCOPE = ("short", "to open", "to close", "option", "assigned", "exercise", "expired")


@dataclass
class ConversionResult:
    transactions: list[Transaction] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"row": n, "reason": str, "text": str}

    def skip(self, row: int, reason: str, text: str = "") -> None:
        self.skipped.append({"row": row, "reason": reason, "text": text[:120]})

    def to_dict(self) -> dict:
        return {
            "imported": len(self.transactions),
            "skipped": self.skipped,
            "transactions": [t.to_dict() for t in self.transactions],
        }


def parse_money(raw: str | None) -> Decimal:
    """'$1,234.56' -> 1234.56, '-$4,200.00' -> -4200.00, '(12.50)' -> -12.50, '' -> 0."""
    text = (raw or "").strip()
    if not text or text in {"--", "-"}:
        return Decimal("0")
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return Decimal("0")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {raw!r}") from exc
    return -value if negative else value


def parse_us_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), "%m/%d/%Y").date()


def chronological(transactions: list[Transaction]) -> list[Transaction]:
    """Broker exports list newest first. Reverse so same-day rows keep their real order, then sort."""
    return sorted(reversed(transactions), key=lambda t: t.date)


def looks_like_option(symbol: str) -> bool:
    return " " in symbol.strip() or any(ch.isdigit() for ch in symbol) and len(symbol) > 6
