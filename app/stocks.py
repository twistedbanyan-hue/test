from __future__ import annotations

import datetime as dt
import os
from typing import Optional, Tuple

import pandas as pd
import requests


class StockDataError(RuntimeError):
    pass


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])


def fetch_stooq_daily(symbol: str, *, timeout_s: int = 30) -> pd.DataFrame:
    """
    Attempts to fetch daily OHLCV from Stooq.

    Note: Stooq may require a JavaScript browser verification challenge. This function
    intentionally does NOT attempt to bypass it; if the challenge is detected, it raises.
    """
    url = "https://stooq.com/q/d/l/"
    s = symbol.strip().lower()
    r = requests.get(url, params={"s": s, "i": "d"}, timeout=timeout_s)
    content_type = (r.headers.get("content-type") or "").lower()
    body_lower = (r.text or "").lower()
    if "text/html" in content_type and (
        "requires javascript to verify your browser" in body_lower
        or "/__verify" in body_lower
        or "crypto.subtle.digest" in body_lower
    ):
        raise StockDataError("Stooq requires browser verification (JS challenge). Use another provider or upload a CSV.")
    if not r.ok:
        raise StockDataError(f"Stooq request failed: HTTP {r.status_code}")

    text = (r.text or "").strip()
    if "No data" in text or len(text.splitlines()) < 2:
        return _empty_df()

    from io import StringIO

    df = pd.read_csv(StringIO(text))
    if "Date" not in df.columns:
        return _empty_df()

    df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.date
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def fetch_alphavantage_daily(symbol: str, *, api_key: str, outputsize: str = "compact", timeout_s: int = 30) -> pd.DataFrame:
    """
    Alpha Vantage daily adjusted OHLCV. Requires an API key.
    """
    url = "https://www.alphavantage.co/query"
    r = requests.get(
        url,
        params={
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol.strip().upper(),
            "outputsize": outputsize,  # compact | full
            "apikey": api_key,
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    data = r.json()

    if "Error Message" in data:
        raise StockDataError(data["Error Message"])
    if "Note" in data:
        raise StockDataError(data["Note"])

    ts = data.get("Time Series (Daily)")
    if not isinstance(ts, dict) or not ts:
        return _empty_df()

    rows = []
    for d, v in ts.items():
        try:
            rows.append(
                {
                    "Date": dt.date.fromisoformat(d),
                    "Open": float(v.get("1. open")),
                    "High": float(v.get("2. high")),
                    "Low": float(v.get("3. low")),
                    "Close": float(v.get("4. close")),
                    "Volume": float(v.get("6. volume") or v.get("5. volume") or 0),
                }
            )
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_df()
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def fetch_twelvedata_daily(symbol: str, *, api_key: str, outputsize: int = 5000, timeout_s: int = 30) -> pd.DataFrame:
    """
    Twelve Data daily OHLCV. Requires an API key.
    """
    url = "https://api.twelvedata.com/time_series"
    r = requests.get(
        url,
        params={
            "symbol": symbol.strip().upper(),
            "interval": "1day",
            "outputsize": str(outputsize),
            "apikey": api_key,
            "format": "JSON",
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict) and data.get("status") == "error":
        raise StockDataError(data.get("message") or "Twelve Data error")

    values = (data or {}).get("values")
    if not isinstance(values, list) or not values:
        return _empty_df()

    rows = []
    for v in values:
        try:
            # Twelve Data returns newest-first
            d = v.get("datetime") or v.get("date")
            rows.append(
                {
                    "Date": dt.date.fromisoformat(str(d)[:10]),
                    "Open": float(v.get("open")),
                    "High": float(v.get("high")),
                    "Low": float(v.get("low")),
                    "Close": float(v.get("close")),
                    "Volume": float(v.get("volume") or 0),
                }
            )
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return _empty_df()
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def fetch_stock_daily(symbol: str, *, provider: str) -> pd.DataFrame:
    provider = (provider or "").strip().lower()
    if provider == "stooq":
        return fetch_stooq_daily(symbol)
    if provider == "alphavantage":
        key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
        if not key:
            raise StockDataError("Missing ALPHAVANTAGE_API_KEY environment variable.")
        return fetch_alphavantage_daily(symbol, api_key=key, outputsize="compact")
    if provider == "twelvedata":
        key = os.getenv("TWELVEDATA_API_KEY", "").strip()
        if not key:
            raise StockDataError("Missing TWELVEDATA_API_KEY environment variable.")
        return fetch_twelvedata_daily(symbol, api_key=key)
    raise StockDataError(f"Unknown provider: {provider}")


def last_close(df: pd.DataFrame) -> Optional[Tuple[dt.date, float]]:
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    if "Date" not in row or "Close" not in row:
        return None
    return row["Date"], float(row["Close"])


def pct_change(df: pd.DataFrame, days: int) -> Optional[float]:
    if df is None or df.empty or days <= 0:
        return None
    if len(df) < 2:
        return None
    end = float(df.iloc[-1]["Close"])
    # Find the row closest to N trading days ago (not calendar days).
    idx = max(0, len(df) - 1 - days)
    start = float(df.iloc[idx]["Close"])
    if start == 0:
        return None
    return (end / start - 1.0) * 100.0

