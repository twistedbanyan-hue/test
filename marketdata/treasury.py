from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from .http import get


@dataclass(frozen=True)
class UstParYieldCurvePoint:
    date: str  # MM/DD/YYYY as published on Treasury.gov
    ten_year: Optional[float]
    thirty_year: Optional[float]
    source_url: str


class _TreasuryTableParser(HTMLParser):
    """
    Minimal HTML table parser sufficient for Treasury 'TextView' table.
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_text_parts: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "table":
            # Treasury page has multiple tables; the first big table is what we want.
            if not self._in_table:
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self.rows.append([])
        elif self._in_row and tag in ("td", "th"):
            self._in_cell = True
            self._cell_text_parts = []

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag == "table" and self._in_table:
            # Stop after first table; sufficient for this use case.
            self._in_table = False
        elif tag == "tr" and self._in_row:
            self._in_row = False
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            cell = " ".join("".join(self._cell_text_parts).split()).strip()
            if self.rows:
                self.rows[-1].append(cell)
            self._cell_text_parts = []

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._in_cell and self._in_table:
            self._cell_text_parts.append(data)


def _to_float(v: str) -> Optional[float]:
    v = v.strip()
    if not v or v.upper() == "N/A":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch_ust_10y_30y_from_treasury_gov(*, year: Optional[int] = None) -> UstParYieldCurvePoint:
    """
    Scrape the latest Daily Treasury Par Yield Curve Rates (10Y, 30Y) from Treasury.gov.

    Source page: https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value=<YEAR>
    """
    if year is None:
        year = datetime.now(timezone.utc).year

    url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView"
    resp = get(
        url,
        params={
            "type": "daily_treasury_yield_curve",
            "field_tdr_date_value": str(year),
        },
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
    )

    parser = _TreasuryTableParser()
    parser.feed(resp.text)

    # Find header row with 'Date', '10 Yr', '30 Yr'
    header_idx = None
    for i, row in enumerate(parser.rows):
        norm = [c.strip() for c in row]
        if "Date" in norm and "10 Yr" in norm and "30 Yr" in norm:
            header_idx = i
            break

    if header_idx is None:
        return UstParYieldCurvePoint(date="", ten_year=None, thirty_year=None, source_url=resp.url)

    header = parser.rows[header_idx]
    col_map: Dict[str, int] = {name: idx for idx, name in enumerate(header)}
    date_col = col_map.get("Date")
    ten_col = col_map.get("10 Yr")
    thirty_col = col_map.get("30 Yr")
    if date_col is None or ten_col is None or thirty_col is None:
        return UstParYieldCurvePoint(date="", ten_year=None, thirty_year=None, source_url=resp.url)

    # Rows after header are data; take the last row with a date cell.
    data_rows = parser.rows[header_idx + 1 :]
    last: Optional[Tuple[str, Optional[float], Optional[float]]] = None
    for row in data_rows:
        if len(row) <= max(date_col, ten_col, thirty_col):
            continue
        d = row[date_col].strip()
        if not d or d == "Date":
            continue
        ten = _to_float(row[ten_col])
        thirty = _to_float(row[thirty_col])
        last = (d, ten, thirty)

    if last is None:
        return UstParYieldCurvePoint(date="", ten_year=None, thirty_year=None, source_url=resp.url)

    d, ten, thirty = last
    return UstParYieldCurvePoint(date=d, ten_year=ten, thirty_year=thirty, source_url=resp.url)


@dataclass(frozen=True)
class TreasuryAuctionsRssItem:
    title: str
    link: Optional[str]
    published: Optional[str]


@dataclass(frozen=True)
class TreasuryAuctionsRssFeed:
    kind: str  # announced | auctioned
    url: str
    fetched_at_utc: str
    items: List[TreasuryAuctionsRssItem]


def fetch_treasury_auctions_rss(kind: str = "announced", *, limit: int = 50) -> TreasuryAuctionsRssFeed:
    """
    Fetch TreasuryDirect TA_WS RSS feeds.

    Known endpoints (require permissive Accept header):
    - Announcements: https://www.treasurydirect.gov/TA_WS/securities/announced/rss
    - Results:       https://www.treasurydirect.gov/TA_WS/securities/auctioned/rss
    """
    if kind not in ("announced", "auctioned"):
        raise ValueError("kind must be 'announced' or 'auctioned'")

    url = f"https://www.treasurydirect.gov/TA_WS/securities/{kind}/rss"
    resp = get(url, headers={"Accept": "1/1,*/*"})

    # Parse RSS without extra deps.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    items: List[TreasuryAuctionsRssItem] = []
    if channel is not None:
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip() or None
            pub = (item.findtext("pubDate") or "").strip() or None
            if title:
                items.append(TreasuryAuctionsRssItem(title=title, link=link, published=pub))
            if len(items) >= limit:
                break

    return TreasuryAuctionsRssFeed(
        kind=kind,
        url=resp.url,
        fetched_at_utc=datetime.now(timezone.utc).isoformat(),
        items=items,
    )

