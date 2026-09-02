# Market data fetchers

Small utilities to fetch:

- **JGB yields** (10Y, 30Y, 40Y) via Yahoo Finance
- **UST yields** (10Y, 30Y) via Treasury.gov (with Yahoo fallback)
- **DXY**, **USD/JPY** via Yahoo Finance
- **Gold spot**, **BTC/USD** via Yahoo Finance; **BTC/USD** also via CoinGecko
- **Treasury auction feeds** (announcements + results) via TreasuryDirect TA_WS RSS

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Fetch snapshot (prints JSON)

```bash
python scripts/fetch_market_data.py
```
