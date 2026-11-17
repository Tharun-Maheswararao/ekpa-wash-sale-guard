# Ekpa Wash Sale Guard

Warns you before and after a sale when buying the same stock in **any** of your accounts would disallow your loss.

> **Prototype. Made-up data only. Not tax advice.** The rules follow IRS Publication 550 (2025), Chapter 4, "Wash Sales."
> They have **not** been reviewed by a tax professional yet. See [Questions for tax review](#questions-for-tax-review).

| Feature | What it does |
|---|---|
| **Pre-sale check** | Pick a holding. See the loss, every purchase of that stock in any account in the last 30 days, and the dollars at risk. IRA purchases are flagged separately because that part of the loss is lost for good. |
| **Rebuy lock** | After a loss sale, shows the date when buying back becomes safe in every account, and the loss still at risk until then. |
| **Reinvestment alerts** | Flags any account where automatic dividend reinvestment could buy the same stock inside a window. Gives the estimated shares and dollars, and when it's safe to turn reinvestment back on. |
| **Summary** | Totals this year's disallowed losses across all accounts: deferred into basis vs. lost for good, by account, and by sale. |

## Quick start

```bash
# Backend: rules engine + API
cd backend
uv venv && uv pip install -e ".[dev]"          # or: python -m venv .venv && pip install -e ".[dev]"
.venv/bin/pytest -q                             # 39 tests: 20 rule cases + converters + features + API
.venv/bin/uvicorn washguard.api:app --reload    # http://127.0.0.1:8000/docs

# Front end (second terminal)
cd frontend
npm install
npm run dev                                     # http://localhost:5173, proxies /api to :8000
```

For one process, run `npm run build` in `frontend/`, then start uvicorn. FastAPI serves `frontend/dist` at `/`.
The `Dockerfile` does the same in one container and listens on `$PORT`, the usual setup on Render, Fly or Railway.
**The Dockerfile is untested.** The Docker daemon wasn't running when it was written.

The demo is pinned to **as of Nov 11, 2026** so the locks and alerts stay the same each time you run it.
Change the date in the header to move through time. **Reset demo** restores the sample data.

## The core rules, with numbers

You buy 100 shares at $50 in Account A. You sell them at $40, a $1,000 loss. Two weeks later you buy 100 shares at $42 in Account B.

| Case | Result | Test |
|---|---|---|
| Account B is taxable | $1,000 disallowed and added to basis: $42 + $10 = **$52/share** | `test_01` |
| Account B is an IRA | $1,000 **lost for good**. The IRA shares keep a $42 basis | `test_02` |
| Only 40 shares rebought | 40% disallowed = **$400**; $600 still deductible | `test_03` |
| Rebought on day 31 | No wash sale. Day 30 *is* one | `test_04` |

### How the engine works ([`engine.py`](backend/washguard/engine.py))

1. Every buy and dividend reinvestment becomes a tax lot up front. So a purchase *after* a loss sale is already visible when that sale is processed.
2. Sales are processed in date order. Each takes shares **first in, first out** from its own account and ticker, and is split into one piece per lot.
3. For each losing piece in a **taxable** account, replacement shares are matched. These are same-ticker lots in any account, bought from 30 days before to 30 days after the sale. They are matched **in the order bought** (Pub 550, "More or less stock bought than sold"). Each replacement share can absorb only one loss.
4. A taxable replacement gets the disallowed loss added to its basis. Its holding period also includes the sold shares' holding period. An IRA or Roth IRA replacement makes the loss permanent, with no basis change (Pub 550 trigger 4).
5. When only part of a lot is matched, the lot is split. Every lot is then either fully used as a replacement or not used at all.

Money uses `Decimal` throughout and is rounded to cents only for display.

## The 20 rule tests ([`tests/test_wash_sale_rules.py`](backend/tests/test_wash_sale_rules.py))

These were written before the engine. The first run failed on import, as expected. All 20 passed on the first run of the engine.

| # | Case | Source |
|---|---|---|
| 01–04 | The four cases from the brief (taxable rebuy, IRA rebuy, partial rebuy, day 30 vs 31) | Brief + Pub 550 |
| 05 | Buy 30 days *before* the sale is a wash; 31 days before is not | Pub 550 |
| 06 | Sale at a gain is never a wash sale | Pub 550 |
| 07 | Pub 550 example: $1,000 → $750, rebuy for $800 → basis **$1,050** | Pub 550 |
| 08 | Pub 550 "more or less" Example 1: 75 shares bought before, **$750** disallowed, lot bases **$3,250 / $1,375** | Pub 550 |
| 09 | Pub 550 Example 2: four 50-share buys after; first two get $500 each | Pub 550 |
| 10 | Pub 550 "loss and gain on same day": the **$3,300** loss is disallowed, the $2,500 and $3,000 gains are not netted against it | Pub 550 |
| 11 | The shares you sold aren't their own replacement | Pub 550 definition |
| 12 | Selling part of one purchase: the remaining shares aren't replacements | Rev. Rul. 56-602 ⚠ |
| 13 | One purchase can't wash two losses; the earlier loss is matched first | Design ⚠ |
| 14 | Different ticker (VOO vs IVV) is not matched in v1 | Scope |
| 15 | Chained wash sale: deferred $1,000 rolls into the next loss and the next basis ($54) | Pub 550 |
| 16 | Replacement's holding period includes the sold shares' holding period → long term | Pub 550 |
| 17 | First in, first out lot selection | Brief |
| 18 | Dividend reinvestment of 0.5 shares disallows $5 | Brief + Pub 550 |
| 19 | Reinvestment inside a Roth IRA is permanent | Pub 550 trigger 4 |
| 20 | Sales inside an IRA aren't wash sales | Design ⚠ |

⚠ = engine decision a tax professional must confirm.

## Sample data

Two made-up accounts in [`backend/sample_data/`](backend/sample_data). Neither is real user data, and all prices are fictional.

| File | Account | Format quirks the converter handles |
|---|---|---|
| `individual_brokerage_schwab.csv` | Taxable, reinvests VTI | Title line, `$1,234.56` money, `"03/30/2026 as of 03/27/2026"` trade dates, cash rows, an options row (skipped), totals row |
| `rollover_ira_fidelity.csv` | Traditional IRA, reinvests AAPL / KO / PFE | Leading blank lines, leading spaces, `YOU BOUGHT …` action text, paired dividend + reinvestment rows, footer text |

`portfolio.json` sets the account types, which tickers reinvest dividends, current prices and the next dividend dates.
Each trade in the history shows one rule:

| Ticker | What happens | Shows |
|---|---|---|
| AAPL | Sold at a $1,250 loss Mar 2. Rebought in taxable Mar 20. **And** an IRA reinvestment of 0.0168 sh on Feb 12 | Deferred $1,249.58 + permanent $0.42. The reinvestment is matched first because it was bought first |
| MSFT | Sold at a $2,000 loss Oct 6. The IRA bought 20 sh on Sep 22 | **$1,000 lost for good** |
| KO | Sold at a $900 loss Oct 15. IRA reinvestment on Oct 1 | Small permanent hit ($3.54) from a reinvestment |
| VTI | Sold at a loss Jun 1, rebought Jul 2 (day 31) | Clean, full loss counts |
| NVDA | Held at a $1,500 loss. The IRA bought 25 sh Oct 28 | **Pre-sale check**: selling today loses $625 for good |
| PFE | Sold at a loss Nov 5. The IRA reinvests on Dec 4 | **Reinvestment alert**: switch to cash until Dec 6 |
| AMZN | Sold at a loss Nov 3, no rebuy | **Rebuy lock** until Dec 4 |

### Converters ([`backend/washguard/converters/`](backend/washguard/converters))

There is one module per broker format. Each one turns an upload into the common format, `account_id,date,action,ticker,quantity,price,fees`,
with action `BUY` / `SELL` / `REINVEST`. Rows the converter can't use (cash moves, dividends paid as cash, options, short sales)
are **reported as skipped with a reason**, never dropped silently. `detect()` sniffs the header so uploads can pick the format automatically.
To add a broker, write `parse(text, account_id) -> ConversionResult` and `sniff(text)`, then register it in `__init__.py`.

The Schwab-style and Fidelity-style layouts are modeled on those brokers' history downloads.
**Check both against a current real export before launch.** Brokers change their columns.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state?as_of=` | Accounts, holdings with wash adjustments, prices, import log |
| POST | `/api/presale-check` | `{account_id, ticker, quantity?, price?, sale_date?}` |
| POST | `/api/trades` | Record a trade (the demo's "Record this sale") |
| GET | `/api/rebuy-lock?as_of=` | Locks per ticker, with a safe date and the dollars at risk |
| GET | `/api/drip-alerts?as_of=` | Reinvestment alerts: high / medium / ok |
| GET | `/api/summary?year=&as_of=` | Year totals, by account, every loss sale |
| POST | `/api/upload` | Multipart: `file`, `account_name`, `account_type`, `broker_format`, `drip_tickers` |
| POST | `/api/reset` | Restore sample data |

State is in memory, which suits a demo. A production version would use Ekpa's own account store.

## Questions for tax review

Each one is a choice the engine makes. Every item needs a yes or a correction before anyone outside the team sees this.

1. **Rev. Rul. 56-602.** Selling part of one purchase lot: are the remaining shares *not* replacement shares? (`test_12`)
2. **Competing losses.** Two loss sales share one window and there's one purchase. Is the purchase matched to the *earlier* loss sale? (`test_13`)
3. **Replacements already sold.** Shares bought inside the window but fully sold *before* the loss sale are not treated as replacements in v1. Correct?
4. **Holding period.** For a replacement bought *before* the sale, the new holding start = replacement date − days the old shares were held. Correct?
5. **IRA sales.** Sales inside an IRA are ignored for wash sale purposes. They can't create a deductible loss. (`test_20`)
6. **Reinvestment.** Every reinvestment counts as a purchase on its trade date, even fractional shares. In an IRA the matched part is permanent. (`test_18`, `test_19`)
7. **Trade date.** Uses the trade date, not settlement. Schwab "as of" dates are treated as the trade date.
8. **Same-day order.** When there are same-day buys and sells, file order is kept. Split lots put the adjusted shares first for first-in, first-out.
9. **Rev. Rul. 2008-5.** The IRA rule here cites Pub 550 trigger (4). The ruling's own text wasn't checked for this prototype.

### Known gaps (out of scope for v1)

- **Spouse accounts.** Pub 550 says a spouse's purchase also triggers a wash sale. v1 only sees your own accounts.
- "Substantially identical" funds (VOO vs IVV), options, short sales, other account types (HSA, 529), and lot methods other than first in, first out.
- Dividend dates come from a fixed calendar. Production needs a data feed and record-date eligibility.

## Week 6 checklist

- [ ] Tax professional signs off on the 20 cases and the questions above
- [ ] Verify both converters against current real exports, using a colleague's file with names removed, never committed
- [ ] Deploy (the Dockerfile is untested) and confirm the live link works
- [ ] Record a demo video under 90 seconds, using the script below

### 90-second demo script

| Time | Screen | Say |
|---|---|---|
| 0–10s | Accounts | "Two accounts: a taxable brokerage and a rollover IRA, imported from two different broker CSVs." |
| 10–35s | Pre-sale check (NVDA) | "I want to sell NVDA for a $1,500 loss. But the IRA bought NVDA two weeks ago. $625 of my loss is gone for good. Not deferred, gone." |
| 35–50s | Record → Rebuy lock | "If I sell anyway, here's the date it's safe to buy back, in every account." |
| 50–70s | Reinvestment alerts | "My IRA reinvests PFE dividends on Dec 4, inside the window of last week's PFE loss sale. Switch it to cash until Dec 6." |
| 70–85s | Summary | "This year: $2,878 disallowed, $1,629 of it lost for good to IRA buys." |
| 85–90s | | "Wash Sale Guard: see it before you sell." |
