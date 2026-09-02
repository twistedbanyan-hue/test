# Debt Tracker

A local, no-database market tape for the Japan / Treasury / gold / BTC thesis. One `requests` dependency. CSV append. HTML dashboard you open as a file.

The market will price a break in hours. You will see it in JGB and UST yields before the headlines explain it.

```
debt_tracker/
├── tracker.py               # Daily pull
├── alerts.py                # Thresholds, phases, notifications
├── thresholds.json          # Edit these, don't edit the code
├── scenarios.json           # A/B/C/D cards on the dashboard
├── dashboard.template.html  # Chart shell
├── weekly_checklist.md      # The 15-minute human pass
├── history.csv              # Created on first run
├── last_run.json            # Latest snapshot
├── alerts.json              # Latest phase evaluation
└── dashboard.html           # Open this in a browser
```

## Setup (Mac Mini)

```bash
cd ~/debt_tracker
python3 -m pip install -r requirements.txt
python3 tracker.py
open dashboard.html
```

First run downloads ~90 trading days so the charts are not empty. Later runs only hit the small daily endpoints (MOF current CSV, Treasury XML, Yahoo, CoinGecko, Fiscal Data auctions).

## Cron

```bash
# Weekdays 7:10am America/Chicago — after Japan close, before the US cash open
10 7 * * 1-5 cd ~/debt_tracker && /usr/bin/python3 tracker.py --notify >> logs/cron.log 2>&1
```

`--notify` uses macOS Notification Center on Darwin (`osascript`). `--voice` adds `say`. `--hook './bionic.sh'` pipes the alert JSON to stdin of any command (local voice model, Bionic, a webhook curl, etc.).

Exit codes for wrapping: `0` all-clear or watch, `1` Phase 2, `2` Phase 3.

## What it tracks

| Series | Source |
|---|---|
| JGB 10Y / 30Y / 40Y | [MOF constant-maturity CSV](https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm) |
| UST 10Y / 30Y | [Treasury.gov daily yield curve](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve) |
| DXY, USD/JPY, gold futures fallback | Yahoo Finance chart API |
| Gold spot | gold-api.com |
| BTC + 24h volume | CoinGecko |
| Exchange BTC reserves | CoinMetrics `SplyExNtv` (Glassnode/CryptoQuant class). Optional `GLASSNODE_API_KEY` / `CRYPTOQUANT_API_KEY` |
| IBIT daily flows | Farside scrape + optional `SOSOVALUE_API_KEY`. Strategy 7d US-ETF print as backup |
| MSTR mNAV, Strategy BTC, QTD sales | [Strategy treasury API](https://api.strategy.com/btc/bitcoinKpis) |
| 10Y / 30Y bid-to-cover, tail | [Treasury Fiscal Data auctions](https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/treasury-securities-auctions-data) (TIPS/FRNs stripped) |

Tail = high yield − median yield, in basis points. A failed auction is bid-to-cover below the fail line **or** tendered amount below the offering.

## Phases

**Phase 1 — Pressure Building (Watch)**
- JGB 40Y > 4.5% and climbing
- UST 30Y > 5.0% (buybacks not holding the long end)
- USD/JPY > 170 or < 145 (volatility, not direction)
- Last 3 coupon auctions average bid-to-cover < 2.3x

**Phase 2 — Cracking (Alert)**
- JGB 40Y > 5.0% with a 20bps+ daily move
- UST 30Y > 5.5% with a 15bps+ daily move
- Any 10Y/30Y bid-to-cover < 2.0x
- DXY breaks 95
- Gold and BTC both rising while DXY falls
- USD/JPY ≥ 180 or ≤ 140

**Phase 3 — Musical Chairs (Action)**
- Coupon auction tail > 5bps in the last 14 days, or a failed auction
- DXY < 90
- Gold gaps > 3% in a day
- BTC/gold breaks 30 oz with volume

Edit `thresholds.json` rather than the Python. 30-year tails of 5–8bps happen in ordinary refundings; the 14-day lookback stops a three-week-old print from putting you in Action Mode.

## Scenarios (not forecasts — the map)

| | Name | Prior | Window | BTC outcome |
|---|---|---|---|---|
| A | The Slow Bleed | 40% | 2026–2032 | 4–5x, $250K–$350K |
| B | The Japan Shock | 35% | 2026–2028 | 6–8x, $400K–$600K |
| C | The Treasury Seizure | 15% | 2027–2029 | 10–15x, messy exit |
| D | The Muddle Through | 10% | 2026–2036 | 1–2x, thesis fails |

The dashboard shows a **tape lean** (heuristic scores + those priors). It is a consistency check against the live print, not a model. The stated bet in the source note is Scenario B in 2027–2028; the 10x needs Scenario C (an actual failed auction).

## Honest timeline

| Phase | Window | What to watch |
|---|---|---|
| Pressure Building | Now – mid 2027 | JGB yields, UST bid-to-cover, yen vol |
| Japan Shock | Late 2027 – 2028 | Pension reallocation headlines, auction stress |
| Treasury Seizure | 2028–2029 | If Phase 2 is not managed |
| Resolution | 2029–2031 | New monetary regime, BTC/gold equilibrium |

## Weekly human check

Even with the script, once a week: [weekly_checklist.md](weekly_checklist.md). Brookings/PIIE (Brooks), Setser, Treasury buyback calendar, BOJ minutes, CFTC COT.

## Commands

```bash
python3 tracker.py                 # pull + evaluate + dashboard
python3 tracker.py --pull-only     # write CSV/snapshot only
python3 tracker.py --dry-run       # print, write nothing
python3 tracker.py --backfill 120  # rebuild history from official series
python3 alerts.py                  # re-evaluate last snapshot
python3 alerts.py --self-test      # phase-logic unit check (no network)
```

Optional keys (used when set; otherwise the free fallbacks above):

```bash
export SOSOVALUE_API_KEY=...     # IBIT/US BTC ETF from SoSoValue
export GLASSNODE_API_KEY=...     # exchange.balance
export CRYPTOQUANT_API_KEY=...   # exchange-flows/reserve
```

Farside is scraped with no key. Datacenter IPs often get Cloudflare; a home Mac Mini usually does not.
