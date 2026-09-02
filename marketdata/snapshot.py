from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .coingecko import fetch_simple_price
from .treasury import fetch_treasury_auctions_rss, fetch_ust_10y_30y_from_treasury_gov
from .yahoo import fetch_quote


def _maybe_scale_yahoo_yield(v: Optional[float]) -> Optional[float]:
    """
    Yahoo yield indices sometimes appear as 10x the yield (e.g. 42.0 for 4.2%).
    Heuristic: if value is implausibly high for a yield %, divide by 10.
    """
    if v is None:
        return None
    return v / 10.0 if v > 20 else v


def fetch_snapshot() -> Dict[str, Any]:
    """
    Fetch a compact cross-asset snapshot.

    Sources:
    - JGB 10Y/30Y/40Y: Yahoo Finance (tickers JP10Y=RR, JP30Y=RR, JP40Y=RR)
    - UST 10Y/30Y: Treasury.gov (scrape) with Yahoo fallback (^TNX, ^TYX)
    - DXY, USD/JPY: Yahoo Finance (DX-Y.NYB, JPY=X)
    - Gold spot, BTC/USD: Yahoo Finance (XAUUSD=X, BTC-USD) + CoinGecko (bitcoin)
    - Treasury auctions calendar-ish: TreasuryDirect TA_WS RSS feeds (announced + auctioned)
    """
    fetched_at_utc = datetime.now(timezone.utc).isoformat()

    # Yahoo symbols
    symbols = {
        "dxy": "DX-Y.NYB",
        "usdjpy": "JPY=X",
        "gold_spot": "XAUUSD=X",
        "btc_usd": "BTC-USD",
        "ust_10y": "^TNX",
        "ust_30y": "^TYX",
        "jgb_10y": "JP10Y=RR",
        "jgb_30y": "JP30Y=RR",
        "jgb_40y": "JP40Y=RR",
    }

    yahoo: Dict[str, Any] = {}
    for k, sym in symbols.items():
        q = fetch_quote(sym)
        yahoo[k] = asdict(q)

    # Treasury.gov yields (preferred)
    ust = fetch_ust_10y_30y_from_treasury_gov()
    ust_dict = asdict(ust)

    # Yahoo fallback if Treasury scrape didn't work
    if ust.ten_year is None:
        ust_dict["ten_year"] = _maybe_scale_yahoo_yield(yahoo["ust_10y"]["price"])
        ust_dict["ten_year_source"] = yahoo["ust_10y"]["source_url"]
    if ust.thirty_year is None:
        ust_dict["thirty_year"] = _maybe_scale_yahoo_yield(yahoo["ust_30y"]["price"])
        ust_dict["thirty_year_source"] = yahoo["ust_30y"]["source_url"]

    btc_cg = fetch_simple_price("bitcoin", vs_currency="usd")

    auctions_announced = fetch_treasury_auctions_rss("announced", limit=50)
    auctions_auctioned = fetch_treasury_auctions_rss("auctioned", limit=50)

    return {
        "fetched_at_utc": fetched_at_utc,
        "yahoo": yahoo,
        "ust_par_yield_curve_10y_30y": ust_dict,
        "coingecko": {"bitcoin_usd": asdict(btc_cg)},
        "treasury_auctions_rss": {
            "announced": asdict(auctions_announced),
            "auctioned": asdict(auctions_auctioned),
        },
    }

