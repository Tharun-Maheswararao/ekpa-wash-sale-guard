"""The common format every broker converter produces."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class AccountType(str, Enum):
    TAXABLE = "taxable"
    IRA = "ira"
    ROTH_IRA = "roth_ira"

    @property
    def is_retirement(self) -> bool:
        return self in (AccountType.IRA, AccountType.ROTH_IRA)

    @property
    def label(self) -> str:
        return {"taxable": "Taxable", "ira": "Traditional IRA", "roth_ira": "Roth IRA"}[self.value]


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    REINVEST = "REINVEST"  # dividend reinvestment purchase

    @property
    def is_acquisition(self) -> bool:
        return self in (Action.BUY, Action.REINVEST)


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    type: AccountType
    broker: str = "manual"
    drip_tickers: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "type_label": self.type.label,
            "broker": self.broker,
            "drip_tickers": sorted(self.drip_tickers),
        }


@dataclass(frozen=True)
class Transaction:
    """One trade in the common format. Quantity is always positive; the action gives direction."""

    account_id: str
    date: date
    action: Action
    ticker: str
    quantity: Decimal
    price: Decimal
    fees: Decimal = Decimal("0")
    source: str = ""  # where it came from, e.g. "schwab row 7"

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive: {self}")
        if self.price < 0 or self.fees < 0:
            raise ValueError(f"price and fees can't be negative: {self}")

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "date": self.date.isoformat(),
            "action": self.action.value,
            "ticker": self.ticker,
            "quantity": float(self.quantity),
            "price": float(self.price),
            "fees": float(self.fees),
            "source": self.source,
        }
