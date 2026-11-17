"""FastAPI service for the Wash Sale Guard.

State lives in memory and starts from the made-up sample portfolio. POST /api/reset restores it.
If frontend/dist exists, it is served at / so one process gives you the whole demo.
"""
from __future__ import annotations

import re
import datetime as dt
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import features
from .converters import convert, formats
from .engine import WashSaleDataError, run_engine
from .models import Account, AccountType, Action, Transaction
from .portfolio import Portfolio, load_sample

app = FastAPI(title="Ekpa Wash Sale Guard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

STATE: dict[str, Portfolio] = {"portfolio": load_sample()}
MAX_UPLOAD_BYTES = 2_000_000


def P() -> Portfolio:
    return STATE["portfolio"]


def _as_of(value: date | None) -> date:
    return value or P().as_of


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (features.FeatureError, WashSaleDataError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip("'\"")) from exc


# --- Read endpoints --------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/state")
def state(as_of: date | None = None):
    p, when = P(), _as_of(as_of)
    return {
        "as_of": when.isoformat(),
        "default_as_of": p.as_of.isoformat(),
        "accounts": [a.to_dict() for a in p.accounts],
        "holdings": _guard(features.holdings, p, when),
        "prices": {k: float(v) for k, v in p.prices.items()},
        "import_log": p.import_log,
        "formats": formats(),
        "transaction_count": len(p.transactions),
    }


@app.get("/api/transactions")
def transactions(account_id: str | None = None):
    return [t.to_dict() for t in P().transactions if account_id in (None, t.account_id)]


@app.get("/api/rebuy-lock")
def rebuy_lock(as_of: date | None = None):
    return _guard(features.rebuy_lock, P(), _as_of(as_of))


@app.get("/api/drip-alerts")
def drip_alerts(as_of: date | None = None):
    return _guard(features.drip_alerts, P(), _as_of(as_of))


@app.get("/api/summary")
def summary(year: int | None = None, as_of: date | None = None):
    when = _as_of(as_of)
    return _guard(features.summary, P(), year or when.year, when)


# --- Actions -----------------------------------------------------------------------------------

class PresaleRequest(BaseModel):
    account_id: str
    ticker: str
    sale_date: date | None = None
    price: Decimal | None = Field(default=None, gt=0)
    quantity: Decimal | None = Field(default=None, gt=0)


@app.post("/api/presale-check")
def presale_check(req: PresaleRequest):
    return _guard(features.presale_check, P(), req.account_id, req.ticker, _as_of(req.sale_date),
                  price=req.price, quantity=req.quantity)


class TradeRequest(BaseModel):
    account_id: str
    ticker: str
    action: Action
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)
    date: dt.date | None = None
    fees: Decimal = Field(default=Decimal("0"), ge=0)


@app.post("/api/trades")
def record_trade(req: TradeRequest):
    p = P()
    _guard(p.account, req.account_id)
    trade = Transaction(req.account_id, _as_of(req.date), req.action, req.ticker.upper(), req.quantity, req.price,
                        req.fees, source="recorded in app")
    candidate = p.transactions + [trade]
    _guard(run_engine, p.accounts, candidate)  # reject trades that break the history
    p.transactions = sorted(candidate, key=lambda t: t.date)
    return {"recorded": trade.to_dict()}


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    account_name: str = Form(...),
    account_type: AccountType = Form(...),
    broker_format: str = Form("auto"),
    drip_tickers: str = Form(""),
    replace_account_id: str | None = Form(None),
):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 2 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    p = P()
    account_id = replace_account_id or _new_account_id(p, account_name, account_type)
    format_id, result = _guard(convert, text, account_id, broker_format)
    if not result.transactions:
        raise HTTPException(400, "No trades found in this file. Check the broker format.")
    account = Account(
        id=account_id,
        name=account_name.strip() or account_id,
        type=account_type,
        broker=format_id,
        drip_tickers=frozenset(t.strip().upper() for t in re.split(r"[,\s]+", drip_tickers) if t.strip()),
    )
    accounts = [a for a in p.accounts if a.id != account_id] + [account]
    others = [t for t in p.transactions if t.account_id != account_id]
    merged = sorted(others + result.transactions, key=lambda t: t.date)
    _guard(run_engine, accounts, merged)
    p.accounts, p.transactions = accounts, merged
    p.import_log = [x for x in p.import_log if x["account_id"] != account_id] + [{
        "account_id": account_id, "file": file.filename, "format": format_id,
        "imported": len(result.transactions), "skipped": len(result.skipped)}]
    return {"account": account.to_dict(), "format": format_id, "imported": len(result.transactions),
            "skipped": result.skipped}


@app.post("/api/reset")
def reset():
    STATE["portfolio"] = load_sample()
    return {"ok": True}


def _new_account_id(p: Portfolio, name: str, kind: AccountType) -> str:
    stem = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:16] or kind.value.upper()
    existing = {a.id for a in p.accounts}
    candidate, n = stem, 2
    while candidate in existing:
        candidate, n = f"{stem}-{n}", n + 1
    return candidate


# --- Static front end (production build) --------------------------------------------------------

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        if path and target.is_file() and DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
