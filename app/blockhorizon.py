from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


SUPABASE_URL = "https://zbvrubdalcojapjygbcz.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_RYSDy8FrvWsClNWT9WWg8A_Mb9eCdp9"


def _headers() -> Dict[str, str]:
    k = SUPABASE_PUBLISHABLE_KEY
    return {
        "apikey": k,
        "Authorization": f"Bearer {k}",
        "Accept": "application/json",
    }


def _get_json(path: str, *, params: Optional[Dict[str, Any]] = None, timeout_s: int = 60) -> Any:
    url = f"{SUPABASE_URL}{path}"
    r = requests.get(url, headers=_headers(), params=params, timeout=timeout_s)
    r.raise_for_status()
    return r.json()


def list_charts_by_slug(slugs: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """
    Returns a mapping: slug -> chart row from `charts` table.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for slug in slugs:
        rows = _get_json(
            "/rest/v1/charts",
            params={
                "select": "id,slug,name,visibility,axis_config,toolbar_config,updated_at",
                "slug": f"eq.{slug}",
                "limit": "1",
            },
        )
        if rows:
            out[slug] = rows[0]
    return out


def fetch_signal_metric_history(chart_id: int, *, limit: int = 2000) -> List[Dict[str, Any]]:
    """
    Pulls normalized signal history (0-100) for a chart id.
    """
    rows = _get_json(
        "/rest/v1/signal_metric_history",
        params={
            "select": "date,chart_id,normalized_value",
            "chart_id": f"eq.{chart_id}",
            "order": "date.asc",
            "limit": str(limit),
        },
    )
    return rows or []


def fetch_signal_category_history(*, limit: int = 2000) -> List[Dict[str, Any]]:
    """
    Pulls category-level signal history (if you want to summarize groups).
    """
    rows = _get_json(
        "/rest/v1/signal_category_history",
        params={
            "select": "*",
            "order": "date.asc",
            "limit": str(limit),
        },
    )
    return rows or []


@dataclass(frozen=True)
class PackedSeries:
    """
    BlockHorizon bundles pack points to reduce payload size.
    - t0: starting timestamp in ms
    - v: values
    - d: day-step deltas (days) between points (index aligned with v)
    """

    t0_ms: int
    values: List[float]
    day_steps: List[int]

    def unpack(self) -> List[Tuple[dt.date, float]]:
        ms_per_day = 86_400_000
        t = int(self.t0_ms)
        out: List[Tuple[dt.date, float]] = []
        for i, val in enumerate(self.values):
            if i > 0:
                step_days = self.day_steps[i] if i < len(self.day_steps) else 1
                t += int(step_days) * ms_per_day
            d = dt.datetime.fromtimestamp(t / 1000, tz=dt.timezone.utc).date()
            out.append((d, float(val)))
        return out


def _parse_packed(packed: Dict[str, Any]) -> Optional[PackedSeries]:
    if not isinstance(packed, dict):
        return None
    if "t0" not in packed or "v" not in packed:
        return None
    if not isinstance(packed.get("v"), list):
        return None
    day_steps = packed.get("d") if isinstance(packed.get("d"), list) else []
    return PackedSeries(t0_ms=int(packed["t0"]), values=list(packed["v"]), day_steps=list(day_steps))


def fetch_bundle(resolution: str) -> Any:
    """
    Fetches BlockHorizon bundle payload. Resolutions observed:
    - dashboard
    - downsampled_v2 / full_v2
    - downsampled / full
    """
    return _get_json("/functions/v1/bundle_handler/serve", params={"resolution": resolution}, timeout_s=120)


def find_chart_in_bundle(bundle: Any, slug: str) -> Optional[Dict[str, Any]]:
    if isinstance(bundle, dict) and "charts" in bundle:
        charts = bundle.get("charts") or []
    else:
        charts = bundle
    if not isinstance(charts, list):
        return None
    for c in charts:
        if isinstance(c, dict) and c.get("slug") == slug:
            return c
    return None


def extract_first_series_points(chart_obj: Dict[str, Any], *, prefer: str = "downsampled") -> List[Tuple[dt.date, float]]:
    """
    Extracts first series from a chart in a bundle.
    prefer:
      - "downsampled": use `pd` if present
      - "full": use `pf` if present
    """
    series = chart_obj.get("series") or []
    if not series:
        return []
    s0 = series[0]
    if not isinstance(s0, dict):
        return []
    packed_key = "pd" if prefer == "downsampled" else "pf"
    packed = s0.get(packed_key) or s0.get("pd") or s0.get("pf")
    ps = _parse_packed(packed) if isinstance(packed, dict) else None
    return ps.unpack() if ps else []

