from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .http import get


@dataclass(frozen=True)
class CoinGeckoSimplePrice:
    asset_id: str
    vs_currency: str
    price: Optional[float]
    fetched_at_utc: str
    source_url: str


def fetch_simple_price(asset_id: str, *, vs_currency: str = "usd") -> CoinGeckoSimplePrice:
    url = "https://api.coingecko.com/api/v3/simple/price"
    resp = get(url, params={"ids": asset_id, "vs_currencies": vs_currency})
    data = resp.json()

    price = None
    try:
        price = float((data.get(asset_id) or {}).get(vs_currency))
    except (TypeError, ValueError):
        price = None

    return CoinGeckoSimplePrice(
        asset_id=asset_id,
        vs_currency=vs_currency,
        price=price,
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        source_url=resp.url,
    )

