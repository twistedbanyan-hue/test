from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .http import get


@dataclass(frozen=True)
class YahooQuote:
    symbol: str
    price: Optional[float]
    currency: Optional[str]
    timestamp_utc: Optional[str]
    exchange: Optional[str]
    source_url: str


def _parse_timestamp(ts: Optional[int]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def fetch_quote(symbol: str) -> YahooQuote:
    """
    Fetch latest quote via Yahoo's public chart endpoint.

    Notes:
    - This uses an unofficial endpoint but is widely used.
    - For yield indices like ^TNX/^TYX the returned "price" is the displayed index value.
    """
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    resp = get(url, params={"interval": "1d", "range": "5d"})
    data: Dict[str, Any] = resp.json()

    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return YahooQuote(
            symbol=symbol,
            price=None,
            currency=None,
            timestamp_utc=None,
            exchange=None,
            source_url=resp.url,
        )

    r0 = result[0]
    meta = r0.get("meta") or {}
    price = meta.get("regularMarketPrice")
    currency = meta.get("currency")
    exchange = meta.get("exchangeName") or meta.get("fullExchangeName")
    timestamp_utc = _parse_timestamp(meta.get("regularMarketTime"))

    try:
        price_f = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_f = None

    return YahooQuote(
        symbol=symbol,
        price=price_f,
        currency=str(currency) if currency is not None else None,
        timestamp_utc=timestamp_utc,
        exchange=str(exchange) if exchange is not None else None,
        source_url=resp.url,
    )


def fetch_quotes(symbols: Tuple[str, ...]) -> Dict[str, YahooQuote]:
    return {s: fetch_quote(s) for s in symbols}

