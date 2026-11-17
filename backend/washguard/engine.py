"""Cross-account wash sale rules engine (v1).

How it works
------------
1. Every acquisition (BUY or REINVEST) becomes a tax lot up front, in date order. That way a
   purchase *after* a loss sale is already visible when the sale is processed.
2. Sales are processed in date order. Each sale takes shares first in, first out from its own
   account and ticker. It is split into one Disposition per lot it touches.
3. For each Disposition at a loss in a taxable account, replacement shares are matched. These
   are lots of the same ticker, in any account, acquired within 30 days before or after the sale.
   They are matched in the order bought (Pub 550, "more or less stock bought than sold"). Shares
   from the same purchase as the sold shares never count (Rev. Rul. 56-602). Each replacement
   share absorbs at most one loss.
4. A taxable replacement gets the disallowed loss added to its basis and inherits the sold
   shares' holding period. An IRA or Roth IRA replacement makes the loss permanent, with no
   basis change.

Lots are split when only part of one is matched, so each lot is either fully used as a
replacement or not used at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .models import Account, AccountType, Action, Transaction

WINDOW_DAYS = 30
ZERO = Decimal("0")


class WashSaleDataError(ValueError):
    """The transaction history can't be processed, e.g. selling shares that were never bought."""


def add_one_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + 1, day=28)


@dataclass
class Lot:
    lot_id: str
    account_id: str
    ticker: str
    acquired: date
    order: int                 # position of the acquiring trade in date order
    tx_index: int              # position of the acquiring trade in the input list
    action: Action
    quantity: Decimal          # shares still open
    original_quantity: Decimal
    cost_per_share: Decimal    # price plus fees, before any wash adjustment
    adjustment_per_share: Decimal = ZERO
    holding_start: date | None = None
    used_as_replacement: bool = False

    def __post_init__(self):
        if self.holding_start is None:
            self.holding_start = self.acquired

    @property
    def basis_per_share(self) -> Decimal:
        return self.cost_per_share + self.adjustment_per_share

    @property
    def basis(self) -> Decimal:
        return self.quantity * self.basis_per_share

    @property
    def wash_adjustment(self) -> Decimal:
        return self.quantity * self.adjustment_per_share

    def split(self, shares: Decimal, suffix: int) -> "Lot":
        """Carve `shares` off into a new lot with identical history."""
        assert ZERO < shares < self.quantity
        self.quantity -= shares
        return Lot(
            lot_id=f"{self.lot_id}.{suffix}",
            account_id=self.account_id,
            ticker=self.ticker,
            acquired=self.acquired,
            order=self.order,
            tx_index=self.tx_index,
            action=self.action,
            quantity=shares,
            original_quantity=shares,
            cost_per_share=self.cost_per_share,
            adjustment_per_share=self.adjustment_per_share,
            holding_start=self.holding_start,
            used_as_replacement=self.used_as_replacement,
        )


@dataclass(frozen=True)
class WashMatch:
    """Replacement shares matched to (part of) a loss."""

    lot_id: str
    account_id: str
    account_type: AccountType
    acquired: date
    action: Action
    tx_index: int
    shares: Decimal
    disallowed: Decimal
    permanent: bool  # True when the replacement is in an IRA or Roth IRA


@dataclass
class Disposition:
    """The part of one sale that came from one lot."""

    tx_index: int
    account_id: str
    account_type: AccountType
    ticker: str
    sale_date: date
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    lot_id: str
    lot_tx_index: int
    acquired: date
    holding_start: date
    matches: list[WashMatch] = field(default_factory=list)

    @property
    def tax_reportable(self) -> bool:
        return self.account_type == AccountType.TAXABLE

    @property
    def gain_loss(self) -> Decimal:
        return self.proceeds - self.cost_basis

    @property
    def is_loss(self) -> bool:
        return self.gain_loss < 0

    @property
    def disallowed(self) -> Decimal:
        return sum((m.disallowed for m in self.matches), ZERO)

    @property
    def disallowed_permanent(self) -> Decimal:
        return sum((m.disallowed for m in self.matches if m.permanent), ZERO)

    @property
    def disallowed_deferred(self) -> Decimal:
        return self.disallowed - self.disallowed_permanent

    @property
    def matched_shares(self) -> Decimal:
        return sum((m.shares for m in self.matches), ZERO)

    @property
    def allowed_gain_loss(self) -> Decimal:
        return self.gain_loss + self.disallowed

    @property
    def loss_per_share(self) -> Decimal:
        return -self.gain_loss / self.quantity if self.is_loss else ZERO

    @property
    def term(self) -> str:
        return "long" if self.sale_date > add_one_year(self.holding_start) else "short"


@dataclass
class EngineResult:
    accounts: dict[str, Account]
    transactions: list[Transaction]
    lots: list[Lot]
    dispositions: list[Disposition]

    def open_lots(self, account_id: str | None = None, ticker: str | None = None) -> list[Lot]:
        found = [
            lot for lot in self.lots
            if lot.quantity > 0
            and (account_id is None or lot.account_id == account_id)
            and (ticker is None or lot.ticker == ticker)
        ]
        return sorted(found, key=lambda lot: (lot.account_id, lot.ticker, lot.order, lot.lot_id))

    def dispositions_for(self, tx_index: int) -> list[Disposition]:
        return [d for d in self.dispositions if d.tx_index == tx_index]


def run_engine(accounts: list[Account], transactions: list[Transaction]) -> EngineResult:
    by_id = {a.id: a for a in accounts}
    unknown = {t.account_id for t in transactions} - by_id.keys()
    if unknown:
        raise WashSaleDataError(f"Transactions reference unknown accounts: {sorted(unknown)}")

    ordered = sorted(enumerate(transactions), key=lambda pair: (pair[1].date, pair[0]))

    # Each book is one account + ticker, lots kept in FIFO order. Splits are inserted in place.
    books: dict[tuple[str, str], list[Lot]] = {}
    all_lots: list[Lot] = []
    for order, (index, t) in enumerate(ordered):
        if not t.action.is_acquisition:
            continue
        lot = Lot(
            lot_id=f"L{index}",
            account_id=t.account_id,
            ticker=t.ticker,
            acquired=t.date,
            order=order,
            tx_index=index,
            action=t.action,
            quantity=t.quantity,
            original_quantity=t.quantity,
            cost_per_share=(t.quantity * t.price + t.fees) / t.quantity,
        )
        books.setdefault((t.account_id, t.ticker), []).append(lot)
        all_lots.append(lot)

    split_counter = [0]

    def split_in_book(lot: Lot, shares: Decimal) -> Lot:
        split_counter[0] += 1
        part = lot.split(shares, split_counter[0])
        book = books[(lot.account_id, lot.ticker)]
        book.insert(book.index(lot), part)  # matched shares sit first among same-day shares
        all_lots.append(part)
        return part

    dispositions: list[Disposition] = []
    for order, (index, t) in enumerate(ordered):
        if t.action != Action.SELL:
            continue
        account = by_id[t.account_id]
        book = books.get((t.account_id, t.ticker), [])
        net_per_share = (t.quantity * t.price - t.fees) / t.quantity

        # 1. First in, first out from lots this account already held.
        remaining = t.quantity
        sold: list[Disposition] = []
        for lot in book:
            if remaining == 0 or lot.order > order:
                break
            if lot.quantity == 0:
                continue
            take = min(remaining, lot.quantity)
            sold.append(Disposition(
                tx_index=index,
                account_id=t.account_id,
                account_type=account.type,
                ticker=t.ticker,
                sale_date=t.date,
                quantity=take,
                proceeds=take * net_per_share,
                cost_basis=take * lot.basis_per_share,
                lot_id=lot.lot_id,
                lot_tx_index=lot.tx_index,
                acquired=lot.acquired,
                holding_start=lot.holding_start,
            ))
            lot.quantity -= take
            remaining -= take
        if remaining > 0:
            raise WashSaleDataError(
                f"{t.date} {t.account_id}: sells {t.quantity} {t.ticker} but only "
                f"{t.quantity - remaining} shares were bought before then. Is the history complete?"
            )

        # 2. Match replacement shares for each losing piece of a taxable sale.
        if account.type == AccountType.TAXABLE:
            for piece in sold:
                if piece.is_loss:
                    _match_replacements(piece, books, by_id, split_in_book)
        dispositions.extend(sold)

    return EngineResult(accounts=by_id, transactions=list(transactions), lots=all_lots, dispositions=dispositions)


def _match_replacements(piece: Disposition, books, accounts: dict[str, Account], split_in_book) -> None:
    start = piece.sale_date - timedelta(days=WINDOW_DAYS)
    end = piece.sale_date + timedelta(days=WINDOW_DAYS)
    candidates = []
    for (_, ticker), book in books.items():
        if ticker != piece.ticker:
            continue
        for position, lot in enumerate(book):
            if (
                start <= lot.acquired <= end
                and lot.quantity > 0
                and not lot.used_as_replacement
                and lot.tx_index != piece.lot_tx_index  # same purchase as the sold shares
            ):
                candidates.append((lot.acquired, lot.order, position, lot))
    candidates.sort(key=lambda c: c[:3])

    loss_per_share = piece.loss_per_share
    held_days = (piece.sale_date - piece.holding_start).days
    remaining = piece.quantity
    for *_, lot in candidates:
        if remaining == 0:
            break
        shares = min(remaining, lot.quantity)
        target = lot if shares == lot.quantity else split_in_book(lot, shares)
        target.used_as_replacement = True
        account_type = accounts[target.account_id].type
        permanent = account_type.is_retirement
        if not permanent:
            target.adjustment_per_share += loss_per_share
            target.holding_start = target.acquired - timedelta(days=held_days)
        piece.matches.append(WashMatch(
            lot_id=target.lot_id,
            account_id=target.account_id,
            account_type=account_type,
            acquired=target.acquired,
            action=target.action,
            tx_index=target.tx_index,
            shares=shares,
            disallowed=loss_per_share * shares,
            permanent=permanent,
        ))
        remaining -= shares
