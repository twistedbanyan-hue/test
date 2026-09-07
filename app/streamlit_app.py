from __future__ import annotations

import datetime as dt
from typing import List, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

from app.blockhorizon import (
    extract_first_series_points,
    fetch_bundle,
    fetch_signal_metric_history,
    list_charts_by_slug,
    find_chart_in_bundle,
)
from app.config import load_config
from app.stocks import StockDataError, fetch_stock_daily, last_close, pct_change


st.set_page_config(page_title="Portfolio + BlockHorizon", layout="wide")


@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_bundle(resolution: str):
    return fetch_bundle(resolution)

@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_btc_usd_close_df():
    """
    Always pulls BTC-USD close from BlockHorizon so it works without stock data keys.
    """
    bundle = fetch_bundle("downsampled_v2")
    chart_obj = find_chart_in_bundle(bundle, "price")
    points = extract_first_series_points(chart_obj, prefer="downsampled") if chart_obj else []
    df = _points_to_df(points).rename(columns={"date": "Date", "value": "Close"})
    return df


@st.cache_data(ttl=60 * 60, show_spinner=False)
def cached_chart_rows(slugs: List[str]):
    return list_charts_by_slug(slugs)


@st.cache_data(ttl=60 * 60, show_spinner=False)
def cached_signal_history(chart_id: int):
    return fetch_signal_metric_history(chart_id, limit=5000)


@st.cache_data(ttl=60 * 30, show_spinner=False)
def cached_stock_df(symbol: str, provider: str):
    return fetch_stock_daily(symbol, provider=provider)


def _window(df: pd.DataFrame, days: int) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if "Date" not in df.columns:
        return df
    cutoff = dt.date.today() - dt.timedelta(days=days)
    return df[df["Date"] >= cutoff].copy()


def _points_to_df(points: List[Tuple[dt.date, float]]) -> pd.DataFrame:
    if not points:
        return pd.DataFrame(columns=["date", "value"])
    return pd.DataFrame(points, columns=["date", "value"])


cfg = load_config()

st.title("Portfolio dashboard (Stocks + BlockHorizon)")
st.caption("Edit `portfolio.yaml` (or use the sidebar) to include your stocks and BTC on-chain charts.")

with st.sidebar:
    st.subheader("Your stocks")
    symbols_text = st.text_area(
        "Tickers (one per line).",
        value="\n".join(cfg.stock_symbols),
        height=160,
    )
    stock_symbols = [s.strip().upper() for s in symbols_text.splitlines() if s.strip()]

    stock_provider = st.selectbox(
        "Stock data source",
        options=["CSV upload", "Alpha Vantage (API key)", "Twelve Data (API key)", "Stooq (may be blocked)"],
        index=0,
        help=(
            "If you choose an API provider, set an environment variable before running:\n"
            "- ALPHAVANTAGE_API_KEY\n"
            "- TWELVEDATA_API_KEY\n\n"
            "CSV upload expects columns: Symbol, Date, Close (Open/High/Low/Volume optional)."
        ),
    )

    uploaded_prices = None
    if stock_provider == "CSV upload":
        uploaded_prices = st.file_uploader("Upload prices CSV", type=["csv"])

    st.subheader("BlockHorizon charts")
    slugs_text = st.text_area(
        "Chart slugs (one per line).",
        value="\n".join(cfg.bh_chart_slugs),
        height=160,
    )
    bh_slugs = [s.strip() for s in slugs_text.splitlines() if s.strip()]

    st.subheader("Display")
    window_days = st.slider("Chart window (calendar days)", min_value=30, max_value=3650, value=cfg.default_window_days, step=30)
    bundle_resolution = st.selectbox(
        "BlockHorizon bundle resolution",
        options=["dashboard", "downsampled_v2", "full_v2", "downsampled", "full"],
        index=1,
        help="downsampled_v2 is smaller/faster; full_v2 is larger/more detailed.",
    )
    prefer_points = st.selectbox("Prefer points", options=["downsampled", "full"], index=0)


col1, col2 = st.columns([1.2, 1.0], gap="large")

with col1:
    st.subheader("Stocks")
    if not stock_symbols:
        st.info("Add stock tickers in the sidebar to populate this section.")
    else:
        provider_key = {
            "CSV upload": "csv",
            "Alpha Vantage (API key)": "alphavantage",
            "Twelve Data (API key)": "twelvedata",
            "Stooq (may be blocked)": "stooq",
        }[stock_provider]

        uploaded_df = None
        if provider_key == "csv":
            if uploaded_prices is not None:
                try:
                    uploaded_df = pd.read_csv(uploaded_prices)
                    uploaded_df.columns = [c.strip() for c in uploaded_df.columns]
                except Exception as e:
                    st.error(f"Failed to read CSV: {e}")
                    uploaded_df = None
            else:
                st.warning("Upload a prices CSV to populate stock charts.")

        rows = []
        for sym in stock_symbols:
            try:
                if sym.upper() in ("BTC-USD", "BTCUSD"):
                    df = cached_btc_usd_close_df()
                    df = df.copy()
                elif provider_key == "csv":
                    if uploaded_df is None or uploaded_df.empty:
                        raise StockDataError("No CSV uploaded.")
                    if "Symbol" not in uploaded_df.columns or "Date" not in uploaded_df.columns or "Close" not in uploaded_df.columns:
                        raise StockDataError("CSV must include columns: Symbol, Date, Close.")
                    df = uploaded_df[uploaded_df["Symbol"].astype(str).str.upper() == sym.upper()].copy()
                    if df.empty:
                        raise StockDataError("No rows for this symbol in uploaded CSV.")
                    df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce").dt.date
                    for c in ["Open", "High", "Low", "Close", "Volume"]:
                        if c in df.columns:
                            df[c] = pd.to_numeric(df[c], errors="coerce")
                    df = df.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
                else:
                    df = cached_stock_df(sym, provider_key)
                lc = last_close(df)
                chg_30 = pct_change(df, 30)
                chg_252 = pct_change(df, 252)
                rows.append(
                    {
                        "symbol": sym,
                        "last_date": lc[0].isoformat() if lc else None,
                        "last_close": lc[1] if lc else None,
                        "chg_30d_%": round(chg_30, 2) if chg_30 is not None else None,
                        "chg_1y_%": round(chg_252, 2) if chg_252 is not None else None,
                    }
                )
            except Exception as e:
                rows.append({"symbol": sym, "error": str(e)})

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        sym_to_plot = st.selectbox("Plot stock", options=stock_symbols, index=0)
        try:
            if sym_to_plot.upper() in ("BTC-USD", "BTCUSD"):
                sdf = cached_btc_usd_close_df()
            elif provider_key == "csv":
                if uploaded_df is None or uploaded_df.empty:
                    sdf = pd.DataFrame()
                else:
                    sdf = uploaded_df[uploaded_df["Symbol"].astype(str).str.upper() == sym_to_plot.upper()].copy()
                    sdf["Date"] = pd.to_datetime(sdf["Date"], utc=True, errors="coerce").dt.date
                    sdf["Close"] = pd.to_numeric(sdf["Close"], errors="coerce")
                    sdf = sdf.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
            else:
                sdf = cached_stock_df(sym_to_plot, provider_key)
        except Exception:
            sdf = pd.DataFrame()

        sdf = _window(sdf, window_days)
        if sdf is None or sdf.empty:
            if provider_key in ("alphavantage", "twelvedata"):
                st.warning("No stock data loaded. If you picked an API provider, set its API key env var before running.")
            else:
                st.warning(f"No data for {sym_to_plot}.")
        else:
            fig = px.line(sdf, x="Date", y="Close", title=f"{sym_to_plot} close")
            fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=360)
            st.plotly_chart(fig, use_container_width=True)


with col2:
    st.subheader("Bitcoin (BlockHorizon)")

    try:
        bundle = cached_bundle(bundle_resolution)
    except Exception as e:
        st.error(f"Failed to load BlockHorizon bundle: {e}")
        bundle = None

    chart_rows = cached_chart_rows(bh_slugs) if bh_slugs else {}

    # Quick “today” tiles using the dashboard bundle when available.
    if bundle_resolution == "dashboard" and isinstance(bundle, dict):
        st.markdown("**Dashboard highlights (from `resolution=dashboard`)**")
        featured = bundle.get("featured") or {}
        if featured:
            st.write(
                {
                    "featured_chart": featured.get("chart_name"),
                    "event": (featured.get("event") or {}).get("headline"),
                    "run_day": featured.get("run_day"),
                }
            )

    if not bh_slugs:
        st.info("Add BlockHorizon chart slugs in the sidebar (e.g. `price`, `nupl`, `blockhorizon-index`).")
    elif bundle is None:
        st.stop()
    else:
        # Summary table
        summary = []
        for slug in bh_slugs:
            row = chart_rows.get(slug) or {}
            chart_obj = find_chart_in_bundle(bundle, slug) if bundle is not None else None
            points = extract_first_series_points(chart_obj, prefer=prefer_points) if chart_obj else []
            last = points[-1] if points else None
            summary.append(
                {
                    "slug": slug,
                    "name": row.get("name"),
                    "chart_id": row.get("id"),
                    "last_date": last[0].isoformat() if last else None,
                    "last_value": round(last[1], 6) if last else None,
                }
            )

        st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

        slug_to_plot = st.selectbox("Plot BlockHorizon chart", options=bh_slugs, index=0)
        chart_obj = find_chart_in_bundle(bundle, slug_to_plot)
        points = extract_first_series_points(chart_obj, prefer=prefer_points) if chart_obj else []
        bdf = _points_to_df(points)
        bdf = _window(bdf.rename(columns={"date": "Date", "value": "Value"}), window_days)

        if bdf.empty:
            st.warning("No series data found for that slug in this bundle resolution.")
        else:
            fig = px.line(bdf, x="Date", y="Value", title=slug_to_plot)
            fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=360)
            st.plotly_chart(fig, use_container_width=True)

        # Signal history (0-100), if we can map slug -> chart_id
        chart_id = (chart_rows.get(slug_to_plot) or {}).get("id")
        if chart_id is not None:
            sig = cached_signal_history(int(chart_id))
            sdf = pd.DataFrame(sig)
            if not sdf.empty and "date" in sdf.columns:
                sdf["date"] = pd.to_datetime(sdf["date"]).dt.date
                sdf = sdf.rename(columns={"date": "Date", "normalized_value": "Signal"})
                sdf = _window(sdf, window_days)
                st.markdown("**Signal score (0–100)**")
                sfig = px.line(sdf, x="Date", y="Signal", title=f"{slug_to_plot} signal score")
                sfig.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=260)
                st.plotly_chart(sfig, use_container_width=True)

