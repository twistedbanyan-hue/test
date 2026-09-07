from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass(frozen=True)
class AppConfig:
    stock_symbols: List[str]
    bh_chart_slugs: List[str]
    default_window_days: int


def load_config(path: Optional[str] = None) -> AppConfig:
    """
    Loads config from YAML.
    If `path` is not provided, looks for `portfolio.yaml` in repo root.
    Falls back to sensible defaults if missing.
    """
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = Path(path) if path else (repo_root / "portfolio.yaml")
    data: Dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    portfolio = data.get("portfolio") or {}
    bh = data.get("blockhorizon") or {}
    ui = data.get("ui") or {}

    stock_symbols = portfolio.get("stocks") or ["AAPL.US", "MSFT.US", "SPY.US"]
    bh_chart_slugs = bh.get("chart_slugs") or ["price", "blockhorizon-index", "nupl", "percent-supply-in-profit"]
    default_window_days = int(ui.get("default_window_days") or 365)

    # Normalize
    stock_symbols = [str(s).strip().upper() for s in stock_symbols if str(s).strip()]
    bh_chart_slugs = [str(s).strip() for s in bh_chart_slugs if str(s).strip()]
    default_window_days = max(30, min(default_window_days, 3650))

    return AppConfig(
        stock_symbols=stock_symbols,
        bh_chart_slugs=bh_chart_slugs,
        default_window_days=default_window_days,
    )

