#!/usr/bin/env python3
"""Daily market pull for the debt / Japan / Treasury tracker.

Free sources, no API keys:
  JGB 10Y/30Y/40Y  — Japan Ministry of Finance constant-maturity CSV
  UST 10Y/30Y      — Treasury.gov yield-curve XML, Yahoo ^TNX/^TYX fallback
  DXY, USD/JPY     — Yahoo Finance
  Gold             — gold-api.com spot, Yahoo GC=F fallback
  BTC              — CoinGecko, Yahoo BTC-USD fallback
  Auction results  — Treasury Fiscal Data (bid-to-cover, tail)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "history.csv"
SNAPSHOT_PATH = ROOT / "last_run.json"
UA = {
    "User-Agent": "debt-tracker/1.0 (+https://github.com/twistedbanyan-hue/test; local research)",
    "Accept": "*/*",
}
HISTORY_FIELDS = [
    "date",
    "pulled_at",
    "jgb_10y",
    "jgb_30y",
    "jgb_40y",
    "ust_10y",
    "ust_30y",
    "usd_jpy",
    "dxy",
    "gold",
    "btc",
    "btc_gold_oz",
    "btc_volume",
    "jgb_40y_bps",
    "ust_30y_bps",
    "gold_pct",
    "btc_pct",
    "dxy_pct",
    "usd_jpy_pct",
    "ust_10y_btc",
    "ust_30y_btc",
    "auction_tail_bps",
    "auction_date",
    "avg_btc_3",
    "phase",
]

SESSION = requests.Session()
SESSION.headers.update(UA)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "null", "None", "N/A", "na"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def get_json(url: str, params: dict | None = None, timeout: int = 25) -> Any:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = SESSION.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 — we want any fetch failure recorded
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last_err}")


def get_text(url: str, params: dict | None = None, timeout: int = 40) -> str:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = SESSION.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last_err}")


def parse_date(text: str | None) -> str | None:
    if not text:
        return None
    raw = text.strip().split("T")[0].replace(".", "/")
    try:
        parts = raw.replace("-", "/").split("/")
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError:
        return None
    return None


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_jgb(backfill_days: int = 0) -> dict[str, Any]:
    """Official MOF constant-maturity yields. Current file is one row; history is optional."""
    current_url = (
        "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
    )
    rows = _parse_mof_csv(get_text(current_url))
    history: list[dict[str, Any]] = []
    if backfill_days:
        hist_url = (
            "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
            "historical/jgbcme_all.csv"
        )
        history = _parse_mof_csv(get_text(hist_url, timeout=60))[-backfill_days:]
    latest = rows[-1] if rows else (history[-1] if history else {})
    # Prefer current file if it is newer than the historical tail (MOF lags all.csv by a day).
    if history and latest.get("date") and history[-1].get("date"):
        if latest["date"] < history[-1]["date"]:
            latest = history[-1]
        elif latest["date"] > history[-1]["date"]:
            history.append(latest)
    return {"latest": latest, "history": history, "source": "mof.jgbcme"}


def _parse_mof_csv(text: str) -> list[dict[str, Any]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header_idx = next((i for i, ln in enumerate(lines) if ln.startswith("Date,")), None)
    if header_idx is None:
        return []
    out: list[dict[str, Any]] = []
    for ln in lines[header_idx + 1 :]:
        if ln.startswith(",") or "cannot download" in ln.lower() or ln.startswith('"'):
            continue
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 16:
            continue
        day = parse_date(parts[0])
        if not day:
            continue
        out.append(
            {
                "date": day,
                "jgb_10y": _f(parts[10]),
                "jgb_30y": _f(parts[14]),
                "jgb_40y": _f(parts[15]),
            }
        )
    return out


def fetch_ust_yields() -> dict[str, Any]:
    year = date.today().year
    url = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    xml_text = get_text(url, params={"data": "daily_treasury_yield_curve", "field_tdr_date_value": str(year)})
    ns = {
        "a": "http://www.w3.org/2005/Atom",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    root = ET.fromstring(xml_text.encode("utf-8"))
    rows: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ns):
        props = entry.find(".//m:properties", ns)
        if props is None:
            continue
        def cell(name: str) -> str | None:
            node = props.find(f"d:{name}", ns)
            return None if node is None else node.text

        day = parse_date(cell("NEW_DATE"))
        if not day:
            continue
        rows.append(
            {
                "date": day,
                "ust_10y": _f(cell("BC_10YEAR")),
                "ust_30y": _f(cell("BC_30YEAR")),
            }
        )
    rows.sort(key=lambda r: r["date"])
    latest = rows[-1] if rows else {}
    if not latest:
        tnx = fetch_yahoo("^TNX")
        tyx = fetch_yahoo("^TYX")
        latest = {
            "date": date.today().isoformat(),
            "ust_10y": tnx.get("price"),
            "ust_30y": tyx.get("price"),
        }
        return {"latest": latest, "history": [], "source": "yahoo.^TNX/^TYX"}
    return {"latest": latest, "history": rows[-90:], "source": "treasury.xml"}


def fetch_yahoo(symbol: str, range_: str = "5d") -> dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    payload = get_json(url, params={"interval": "1d", "range": range_})
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
    series: list[dict[str, Any]] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        series.append({"date": day, "close": float(close)})
    price = _f(meta.get("regularMarketPrice"))
    if price is None and series:
        price = series[-1]["close"]
    prev = series[-2]["close"] if len(series) >= 2 else _f(meta.get("chartPreviousClose"))
    pct = None
    if price is not None and prev not in (None, 0):
        pct = (price - prev) / prev * 100.0
    return {
        "symbol": symbol,
        "price": price,
        "prev": prev,
        "pct": pct,
        "history": series,
        "name": meta.get("shortName") or symbol,
    }


def fetch_gold() -> dict[str, Any]:
    """Spot for the level; COMEX GC=F for the daily % (so a basis gap cannot fake Phase 3)."""
    yahoo = fetch_yahoo("GC=F", "3mo")
    spot = None
    try:
        payload = get_json("https://api.gold-api.com/price/XAU")
        spot = _f(payload.get("price"))
    except Exception:
        pass
    return {
        "price": spot if spot is not None else yahoo.get("price"),
        "prev": yahoo.get("prev"),
        "pct": yahoo.get("pct"),
        "history": yahoo.get("history") or [],
        "source": "gold-api + yahoo GC=F" if spot is not None else "yahoo.GC=F",
    }


def fetch_btc() -> dict[str, Any]:
    volume = None
    price = None
    pct = None
    source = "yahoo.BTC-USD"
    try:
        payload = get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        )
        coin = payload["bitcoin"]
        price = _f(coin.get("usd"))
        volume = _f(coin.get("usd_24h_vol"))
        pct = _f(coin.get("usd_24h_change"))
        source = "coingecko"
    except Exception:
        pass
    yahoo = fetch_yahoo("BTC-USD", "3mo")
    if price is None:
        price = yahoo.get("price")
        pct = yahoo.get("pct")
    return {
        "price": price,
        "pct": pct,
        "volume": volume,
        "prev": yahoo.get("prev"),
        "history": yahoo.get("history") or [],
        "source": source,
    }


def fetch_auctions() -> dict[str, Any]:
    fields = (
        "auction_date,security_type,security_term,bid_to_cover_ratio,high_yield,"
        "avg_med_yield,low_yield,offering_amt,total_accepted,total_tendered,"
        "inflation_index_security,floating_rate,reopening"
    )
    completed = get_json(
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query",
        params={
            "filter": "security_term:in:(10-Year,30-Year),inflation_index_security:eq:No",
            "sort": "-auction_date",
            "page[size]": 16,
            "fields": fields,
        },
    ).get("data", [])
    cleaned: list[dict[str, Any]] = []
    for row in completed:
        if str(row.get("floating_rate", "No")).lower() == "yes":
            continue
        btc = _f(row.get("bid_to_cover_ratio"))
        high = _f(row.get("high_yield"))
        med = _f(row.get("avg_med_yield"))
        tail = None if high is None or med is None else round((high - med) * 100.0, 2)
        offering = _f(row.get("offering_amt"))
        tendered = _f(row.get("total_tendered"))
        failed = False
        if btc is not None and btc < 1.0:
            failed = True
        if offering and tendered is not None and tendered < offering:
            failed = True
        cleaned.append(
            {
                "auction_date": row.get("auction_date"),
                "security_type": row.get("security_type"),
                "security_term": row.get("security_term"),
                "bid_to_cover": _round(btc, 3),
                "high_yield": _round(high, 4),
                "avg_med_yield": _round(med, 4),
                "tail_bps": tail,
                "offering_amt": offering,
                "total_tendered": tendered,
                "reopening": row.get("reopening"),
                "failed": failed,
            }
        )
    latest_30 = next((r for r in cleaned if r["security_term"] == "30-Year" and r["bid_to_cover"] is not None), None)
    latest_10 = next((r for r in cleaned if r["security_term"] == "10-Year" and r["bid_to_cover"] is not None), None)
    with_cover = [r for r in cleaned if r["bid_to_cover"] is not None][:3]
    avg_btc_3 = None
    if with_cover:
        avg_btc_3 = round(sum(r["bid_to_cover"] for r in with_cover) / len(with_cover), 3)

    today = date.today().isoformat()
    upcoming = get_json(
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query",
        params={
            "filter": f"auction_date:gte:{today}",
            "sort": "auction_date",
            "page[size]": 12,
            "fields": "auction_date,security_type,security_term,offering_amt,bid_to_cover_ratio",
        },
    ).get("data", [])
    upcoming_out = [
        {
            "auction_date": r.get("auction_date"),
            "security_type": r.get("security_type"),
            "security_term": r.get("security_term"),
            "offering_amt": _f(r.get("offering_amt")),
            "completed": _f(r.get("bid_to_cover_ratio")) is not None,
        }
        for r in upcoming
    ]
    return {
        "latest_30y": latest_30,
        "latest_10y": latest_10,
        "recent": cleaned[:8],
        "upcoming": upcoming_out,
        "avg_btc_3": avg_btc_3,
        "source": "fiscaldata.auctions_query",
    }


# ---------------------------------------------------------------------------
# Snapshot + history
# ---------------------------------------------------------------------------

def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new - old) / old * 100.0


def _bps(new: float | None, old: float | None) -> float | None:
    if new is None or old is None:
        return None
    return (new - old) * 100.0


def _history_map(series: list[dict[str, Any]], value_key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in series:
        val = _f(row.get(value_key) if value_key in row else row.get("close"))
        day = row.get("date")
        if day and val is not None:
            out[day] = val
    return out


def build_snapshot(backfill_days: int = 0) -> dict[str, Any]:
    errors: list[str] = []
    sources: dict[str, str] = {}

    def grab(label: str, fn, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
            sources[label] = result.get("source", label) if isinstance(result, dict) else label
            return result
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
            return {}

    jgb = grab("jgb", fetch_jgb, backfill_days)
    ust = grab("ust", fetch_ust_yields)
    usd_jpy = grab("usd_jpy", fetch_yahoo, "JPY=X", "3mo")
    dxy = grab("dxy", fetch_yahoo, "DX-Y.NYB", "3mo")
    gold = grab("gold", fetch_gold)
    btc = grab("btc", fetch_btc)
    auctions = grab("auctions", fetch_auctions)

    jgb_latest = jgb.get("latest") or {}
    ust_latest = ust.get("latest") or {}
    gold_px = gold.get("price")
    btc_px = btc.get("price")
    ratio = None if not gold_px or not btc_px else btc_px / gold_px

    as_of_candidates = [
        jgb_latest.get("date"),
        ust_latest.get("date"),
        date.today().isoformat(),
    ]
    as_of = max(c for c in as_of_candidates if c)

    # Daily changes: prefer official previous close, then Yahoo prev, then history.csv.
    prior_csv = _last_history_row()
    jgb_hist = jgb.get("history") or []
    jgb_prev = jgb_hist[-2] if len(jgb_hist) >= 2 else {}
    if jgb_prev.get("date") == jgb_latest.get("date") and len(jgb_hist) >= 3:
        jgb_prev = jgb_hist[-3]
    if not jgb_prev and prior_csv:
        jgb_prev = prior_csv

    ust_hist = ust.get("history") or []
    ust_prev = ust_hist[-2] if len(ust_hist) >= 2 else (prior_csv or {})

    quotes = {
        "jgb_10y": _round(jgb_latest.get("jgb_10y"), 3),
        "jgb_30y": _round(jgb_latest.get("jgb_30y"), 3),
        "jgb_40y": _round(jgb_latest.get("jgb_40y"), 3),
        "ust_10y": _round(ust_latest.get("ust_10y"), 3),
        "ust_30y": _round(ust_latest.get("ust_30y"), 3),
        "usd_jpy": _round(usd_jpy.get("price"), 3),
        "dxy": _round(dxy.get("price"), 3),
        "gold": _round(gold_px, 2),
        "btc": _round(btc_px, 2),
        "btc_gold_oz": _round(ratio, 2),
        "btc_volume": _round(btc.get("volume"), 0),
    }
    changes = {
        "jgb_40y_bps": _round(_bps(jgb_latest.get("jgb_40y"), jgb_prev.get("jgb_40y")), 2),
        "ust_30y_bps": _round(_bps(ust_latest.get("ust_30y"), ust_prev.get("ust_30y")), 2),
        "gold_pct": _round(gold.get("pct") if gold.get("pct") is not None else _pct(gold_px, gold.get("prev")), 3),
        "btc_pct": _round(btc.get("pct"), 3),
        "dxy_pct": _round(dxy.get("pct"), 3),
        "usd_jpy_pct": _round(usd_jpy.get("pct"), 3),
    }

    snapshot = {
        "pulled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of,
        "quotes": quotes,
        "changes": changes,
        "auctions": auctions or {},
        "sources": sources,
        "errors": errors,
        "series": {
            "jgb": jgb.get("history") or ([jgb_latest] if jgb_latest else []),
            "ust": ust.get("history") or [],
            "usd_jpy": usd_jpy.get("history") or [],
            "dxy": dxy.get("history") or [],
            "gold": gold.get("history") or [],
            "btc": btc.get("history") or [],
        },
    }
    return snapshot


def _last_history_row() -> dict[str, Any] | None:
    rows = read_history()
    return rows[-1] if rows else None


def read_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _fmt_csv(value: Any) -> str:
    if value is None or value == "":
        return ""
    return str(value)


def upsert_history(snapshot: dict[str, Any], phase: int | None = None) -> None:
    q = snapshot["quotes"]
    c = snapshot["changes"]
    a = snapshot.get("auctions") or {}
    latest_30 = a.get("latest_30y") or {}
    latest_10 = a.get("latest_10y") or {}
    row = {
        "date": snapshot["as_of"],
        "pulled_at": snapshot["pulled_at"],
        "jgb_10y": q.get("jgb_10y"),
        "jgb_30y": q.get("jgb_30y"),
        "jgb_40y": q.get("jgb_40y"),
        "ust_10y": q.get("ust_10y"),
        "ust_30y": q.get("ust_30y"),
        "usd_jpy": q.get("usd_jpy"),
        "dxy": q.get("dxy"),
        "gold": q.get("gold"),
        "btc": q.get("btc"),
        "btc_gold_oz": q.get("btc_gold_oz"),
        "btc_volume": q.get("btc_volume"),
        "jgb_40y_bps": c.get("jgb_40y_bps"),
        "ust_30y_bps": c.get("ust_30y_bps"),
        "gold_pct": c.get("gold_pct"),
        "btc_pct": c.get("btc_pct"),
        "dxy_pct": c.get("dxy_pct"),
        "usd_jpy_pct": c.get("usd_jpy_pct"),
        "ust_10y_btc": (latest_10 or {}).get("bid_to_cover"),
        "ust_30y_btc": (latest_30 or {}).get("bid_to_cover"),
        "auction_tail_bps": (latest_30 or {}).get("tail_bps"),
        "auction_date": (latest_30 or {}).get("auction_date"),
        "avg_btc_3": a.get("avg_btc_3"),
        "phase": phase if phase is not None else "",
    }
    existing = read_history()
    by_date = {r["date"]: r for r in existing if r.get("date")}
    by_date[row["date"]] = {k: _fmt_csv(row.get(k)) for k in HISTORY_FIELDS}
    ordered = sorted(by_date.values(), key=lambda r: r["date"])
    with HISTORY_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def backfill_history(snapshot: dict[str, Any], days: int = 90) -> None:
    """Build a starter CSV from the series we already fetched so charts are not empty."""
    series = snapshot.get("series") or {}
    maps = {
        "jgb_10y": _history_map(series.get("jgb") or [], "jgb_10y"),
        "jgb_30y": _history_map(series.get("jgb") or [], "jgb_30y"),
        "jgb_40y": _history_map(series.get("jgb") or [], "jgb_40y"),
        "ust_10y": _history_map(series.get("ust") or [], "ust_10y"),
        "ust_30y": _history_map(series.get("ust") or [], "ust_30y"),
        "usd_jpy": _history_map(series.get("usd_jpy") or [], "close"),
        "dxy": _history_map(series.get("dxy") or [], "close"),
        "gold": _history_map(series.get("gold") or [], "close"),
        "btc": _history_map(series.get("btc") or [], "close"),
    }
    dates = sorted({d for m in maps.values() for d in m})
    if not dates:
        upsert_history(snapshot)
        return
    dates = dates[-days:]
    existing = {r["date"]: r for r in read_history() if r.get("date")}
    rows: list[dict[str, str]] = []
    prev: dict[str, float | None] = {}
    for day in dates:
        rec: dict[str, Any] = {k: "" for k in HISTORY_FIELDS}
        rec["date"] = day
        rec["pulled_at"] = snapshot["pulled_at"]
        for field, mp in maps.items():
            if day in mp:
                rec[field] = _fmt_csv(_round(mp[day], 4))
        gold_v = _f(rec["gold"])
        btc_v = _f(rec["btc"])
        if gold_v and btc_v:
            rec["btc_gold_oz"] = _fmt_csv(_round(btc_v / gold_v, 2))
        rec["jgb_40y_bps"] = _fmt_csv(_round(_bps(_f(rec["jgb_40y"]), prev.get("jgb_40y")), 2))
        rec["ust_30y_bps"] = _fmt_csv(_round(_bps(_f(rec["ust_30y"]), prev.get("ust_30y")), 2))
        rec["gold_pct"] = _fmt_csv(_round(_pct(_f(rec["gold"]), prev.get("gold")), 3))
        rec["btc_pct"] = _fmt_csv(_round(_pct(_f(rec["btc"]), prev.get("btc")), 3))
        rec["dxy_pct"] = _fmt_csv(_round(_pct(_f(rec["dxy"]), prev.get("dxy")), 3))
        rec["usd_jpy_pct"] = _fmt_csv(_round(_pct(_f(rec["usd_jpy"]), prev.get("usd_jpy")), 3))
        rows.append(rec)
        prev = {k: _f(rec[k]) for k in maps}
        existing[day] = rec
    # Overlay today's official snapshot on top of backfill.
    upsert_history(snapshot)
    # Re-read overlay and keep backfill days that were not today.
    today_row = {r["date"]: r for r in read_history()}
    merged = existing
    merged.update(today_row)
    ordered = sorted(merged.values(), key=lambda r: r["date"])
    with HISTORY_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def save_snapshot(snapshot: dict[str, Any]) -> None:
    slim = {k: v for k, v in snapshot.items() if k != "series"}
    SNAPSHOT_PATH.write_text(json.dumps(slim, indent=2), encoding="utf-8")


def print_snapshot(snapshot: dict[str, Any]) -> None:
    q = snapshot["quotes"]
    c = snapshot["changes"]
    a = snapshot.get("auctions") or {}
    print()
    print(f"  Debt Tracker  {snapshot['as_of']}  pulled {snapshot['pulled_at']}")
    print("  " + "-" * 62)
    def line(label: str, value, suffix: str = "", change=None, change_suffix: str = ""):
        val = "—" if value is None else f"{value:,}" if not isinstance(value, str) else value
        extra = ""
        if change is not None:
            sign = "+" if change > 0 else ""
            extra = f"  ({sign}{change}{change_suffix})"
        print(f"  {label:<18} {val}{suffix}{extra}")

    line("JGB 10Y", q.get("jgb_10y"), "%")
    line("JGB 30Y", q.get("jgb_30y"), "%")
    line("JGB 40Y", q.get("jgb_40y"), "%", c.get("jgb_40y_bps"), " bps")
    line("UST 10Y", q.get("ust_10y"), "%")
    line("UST 30Y", q.get("ust_30y"), "%", c.get("ust_30y_bps"), " bps")
    line("USD/JPY", q.get("usd_jpy"), "", c.get("usd_jpy_pct"), "%")
    line("DXY", q.get("dxy"), "", c.get("dxy_pct"), "%")
    line("Gold", q.get("gold"), "", c.get("gold_pct"), "%")
    line("BTC", q.get("btc"), "", c.get("btc_pct"), "%")
    line("BTC/gold", q.get("btc_gold_oz"), " oz")
    latest_30 = a.get("latest_30y") or {}
    if latest_30:
        print(
            f"  {'30Y auction':<18} {latest_30.get('auction_date')}  "
            f"BTC {latest_30.get('bid_to_cover')}x  tail {latest_30.get('tail_bps')} bps"
        )
    latest_10 = a.get("latest_10y") or {}
    if latest_10:
        print(
            f"  {'10Y auction':<18} {latest_10.get('auction_date')}  "
            f"BTC {latest_10.get('bid_to_cover')}x  tail {latest_10.get('tail_bps')} bps"
        )
    if a.get("avg_btc_3") is not None:
        print(f"  {'Avg BTC last 3':<18} {a['avg_btc_3']}x")
    if snapshot.get("errors"):
        print()
        print("  Fetch warnings:")
        for err in snapshot["errors"]:
            print(f"    - {err}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull JGB/UST/FX/gold/BTC and append history.csv")
    parser.add_argument("--pull-only", action="store_true", help="Skip alerts and dashboard")
    parser.add_argument("--backfill", type=int, nargs="?", const=90, default=None, metavar="DAYS",
                        help="Force-seed history.csv from official series (90 if flag has no number)")
    parser.add_argument("--no-backfill", action="store_true", help="Never download JGB history or seed CSV")
    parser.add_argument("--notify", action="store_true", help="Pass through to alerts.py")
    parser.add_argument("--voice", action="store_true", help="macOS `say` on Phase 2+")
    parser.add_argument("--hook", default="", help="Shell command; alert JSON on stdin")
    parser.add_argument("--dry-run", action="store_true", help="Print snapshot, do not write files")
    args = parser.parse_args(argv)

    if args.no_backfill:
        jgb_hist_days, do_backfill = 0, False
    elif args.backfill is not None:
        jgb_hist_days, do_backfill = args.backfill, True
    elif not HISTORY_PATH.exists():
        jgb_hist_days, do_backfill = 90, True
    else:
        jgb_hist_days, do_backfill = 0, False

    print("Pulling JGB, UST, FX, gold, BTC, auctions...")
    snapshot = build_snapshot(backfill_days=jgb_hist_days)
    print_snapshot(snapshot)

    if args.dry_run:
        return 1 if snapshot.get("errors") else 0

    save_snapshot(snapshot)
    if do_backfill:
        print(f"Backfilling {jgb_hist_days or 90} days into history.csv...")
        backfill_history(snapshot, days=jgb_hist_days or 90)
    else:
        upsert_history(snapshot)

    if args.pull_only:
        return 1 if snapshot.get("errors") else 0

    from alerts import run_alerts

    return run_alerts(notify_on=args.notify, voice=args.voice, hook=args.hook or None)


if __name__ == "__main__":
    sys.exit(main())
