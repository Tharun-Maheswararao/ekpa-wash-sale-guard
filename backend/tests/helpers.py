"""Small builders so each rule test reads like the worked example it encodes."""
from datetime import date, timedelta
from decimal import Decimal

from washguard.models import Account, AccountType, Action, Transaction

TAX_A = Account("A", "Taxable A", AccountType.TAXABLE)
TAX_B = Account("B", "Taxable B", AccountType.TAXABLE)
IRA = Account("IRA", "Traditional IRA", AccountType.IRA)
ROTH = Account("ROTH", "Roth IRA", AccountType.ROTH_IRA)
ACCOUNTS = [TAX_A, TAX_B, IRA, ROTH]

SALE_DAY = date(2026, 3, 2)


def d(value) -> Decimal:
    return Decimal(str(value))


def day(offset: int, base: date = SALE_DAY) -> str:
    """ISO date `offset` calendar days from the base sale date."""
    return (base + timedelta(days=offset)).isoformat()


def tx(account: str, when: str, action: str, qty, price, ticker: str = "XYZ", fees=0) -> Transaction:
    return Transaction(
        account_id=account,
        date=date.fromisoformat(when),
        action=Action(action),
        ticker=ticker,
        quantity=d(qty),
        price=d(price),
        fees=d(fees),
    )


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))
