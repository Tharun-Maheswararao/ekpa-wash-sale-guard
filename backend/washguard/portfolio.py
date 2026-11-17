"""A user's accounts, trade history, prices and dividend calendar, plus the sample data loader."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from .converters import convert
from .engine import EngineResult, run_engine
from .models import Account, AccountType, Transaction

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


@dataclass(frozen=True)
class Dividend:
    ticker: str
    pay_date: date
    amount_per_share: Decimal


@dataclass
class Portfolio:
    as_of: date
    accounts: list[Account]
    transactions: list[Transaction]
    prices: dict[str, Decimal] = field(default_factory=dict)
    dividends: dict[str, list[Dividend]] = field(default_factory=dict)
    import_log: list[dict] = field(default_factory=list)

    def account(self, account_id: str) -> Account:
        for a in self.accounts:
            if a.id == account_id:
                return a
        raise KeyError(f"No account {account_id!r}")

    def history(self, through: date) -> list[Transaction]:
        """Trades on or before `through`. Features never look at trades after their own date."""
        return [t for t in self.transactions if t.date <= through]

    def run(self, through: date) -> EngineResult:
        return run_engine(self.accounts, self.history(through))

    def price(self, ticker: str) -> Decimal | None:
        return self.prices.get(ticker)

    def next_dividend(self, ticker: str, after: date, until: date | None = None) -> Dividend | None:
        for div in sorted(self.dividends.get(ticker, []), key=lambda x: x.pay_date):
            if div.pay_date > after and (until is None or div.pay_date <= until):
                return div
        return None


def load_sample(directory: Path = SAMPLE_DIR) -> Portfolio:
    config = json.loads((directory / "portfolio.json").read_text())
    accounts, transactions, log = [], [], []
    for spec in config["accounts"]:
        account = Account(
            id=spec["id"],
            name=spec["name"],
            type=AccountType(spec["type"]),
            broker=spec["broker"],
            drip_tickers=frozenset(spec.get("drip_tickers", [])),
        )
        accounts.append(account)
        text = (directory / spec["file"]).read_text()
        format_id, result = convert(text, account.id, spec["broker"])
        transactions.extend(result.transactions)
        log.append({"account_id": account.id, "file": spec["file"], "format": format_id,
                    "imported": len(result.transactions), "skipped": len(result.skipped)})
    return Portfolio(
        as_of=date.fromisoformat(config["as_of"]),
        accounts=accounts,
        transactions=sorted(transactions, key=lambda t: t.date),
        prices={k: Decimal(str(v)) for k, v in config.get("prices", {}).items()},
        dividends={
            ticker: [Dividend(ticker, date.fromisoformat(x["pay_date"]), Decimal(str(x["amount_per_share"])))
                     for x in rows]
            for ticker, rows in config.get("dividends", {}).items()
        },
        import_log=log,
    )
