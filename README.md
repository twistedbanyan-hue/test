# Portfolio + BlockHorizon dashboard

This repo contains a small dashboard that combines:

- **Bitcoin on-chain metrics and signal scores** from BlockHorizon (via their public endpoints)
- **Your stock tickers** (daily OHLCV) from a selectable source:
  - CSV upload (recommended, no keys)
  - Alpha Vantage (API key)
  - Twelve Data (API key)

## Quick start

1) Create your config:

```bash
cp portfolio.example.yaml portfolio.yaml
```

2) Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3) Run the app:

```bash
streamlit run app/streamlit_app.py
```

## Add your stocks

Edit `portfolio.yaml` and put your tickers under `portfolio.stocks`, or paste them in the sidebar UI.

Notes:

- From your Apple Stocks watchlist, examples include: `BTC-USD`, `MSTR`, `STRC`, `SPCX`, `CBRS`, `VRT`, `NVT`, `NVDA`.
- `BTC-USD` works out of the box (pulled from BlockHorizon).
- **CSV upload**: upload a CSV with columns `Symbol`, `Date`, `Close` (optional: `Open`, `High`, `Low`, `Volume`).
- **Alpha Vantage**: set `ALPHAVANTAGE_API_KEY` before running.
- **Twelve Data**: set `TWELVEDATA_API_KEY` before running.
