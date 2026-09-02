#!/usr/bin/env python3
"""Threshold checks, phase classification, notifications, dashboard write."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
THRESHOLDS_PATH = ROOT / "thresholds.json"
SCENARIOS_PATH = ROOT / "scenarios.json"
SNAPSHOT_PATH = ROOT / "last_run.json"
HISTORY_PATH = ROOT / "history.csv"
ALERTS_PATH = ROOT / "alerts.json"
DASHBOARD_PATH = ROOT / "dashboard.html"
TEMPLATE_PATH = ROOT / "dashboard.template.html"

PHASE_NAMES = {
    0: "All Clear",
    1: "Phase 1 — Pressure Building (Watch)",
    2: "Phase 2 — Cracking (Alert)",
    3: "Phase 3 — Musical Chairs (Action)",
}


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_history() -> list[dict[str, Any]]:
    import csv

    if not HISTORY_PATH.exists():
        return []
    with HISTORY_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def evaluate(snapshot: dict[str, Any], thresholds: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    q = snapshot.get("quotes") or {}
    c = snapshot.get("changes") or {}
    a = snapshot.get("auctions") or {}
    hits: list[dict[str, Any]] = []

    def add(condition: bool, phase: int, key: str, message_fn, value: Any = None) -> None:
        if condition:
            hits.append({"phase": phase, "key": key, "message": message_fn(), "value": value})

    jgb40 = _f(q.get("jgb_40y"))
    jgb_bps = _f(c.get("jgb_40y_bps"))
    ust30 = _f(q.get("ust_30y"))
    ust_bps = _f(c.get("ust_30y_bps"))
    usd_jpy = _f(q.get("usd_jpy"))
    dxy = _f(q.get("dxy"))
    gold_pct = _f(c.get("gold_pct"))
    btc_pct = _f(c.get("btc_pct"))
    dxy_pct = _f(c.get("dxy_pct"))
    ratio = _f(q.get("btc_gold_oz"))
    volume = _f(q.get("btc_volume"))
    avg_btc_3 = _f(a.get("avg_btc_3"))

    jgb_cfg = thresholds["jgb_40y"]
    ust_cfg = thresholds["ust_30y"]
    yen_cfg = thresholds["usd_jpy"]
    dxy_cfg = thresholds["dxy"]
    btc_cfg = thresholds["treasury_bid_to_cover"]
    ratio_cfg = thresholds["btc_gold_ratio"]
    tail_cfg = thresholds["treasury_tail_bps"]
    gold_gap_cfg = thresholds["gold_gap_pct"]
    vol_cfg = thresholds["btc_volume_usd"]
    widen_cfg = thresholds["gold_btc_gap"]

    # --- Phase 1: Pressure Building ---
    add(
        jgb40 is not None and jgb_bps is not None and jgb40 > jgb_cfg["watch"] and jgb_bps > 0,
        1, "jgb_40y_watch",
        lambda: f"JGB 40Y {jgb40:.3f}% > {jgb_cfg['watch']}% and climbing ({jgb_bps:+.1f} bps)",
        jgb40,
    )
    add(
        ust30 is not None and ust30 > ust_cfg["watch"],
        1, "ust_30y_watch",
        lambda: f"UST 30Y {ust30:.3f}% > {ust_cfg['watch']}% despite buybacks — long end not cooperating",
        ust30,
    )
    yen_watch = usd_jpy is not None and (usd_jpy > yen_cfg["watch_high"] or usd_jpy < yen_cfg["watch_low"])
    add(
        yen_watch,
        1, "usd_jpy_vol",
        lambda: f"USD/JPY {usd_jpy:.1f} outside {yen_cfg['watch_low']}–{yen_cfg['watch_high']} (vol, not direction)",
        usd_jpy,
    )
    add(
        avg_btc_3 is not None and avg_btc_3 < btc_cfg["watch_trend"],
        1, "auction_trend",
        lambda: f"Last 3 long-end auctions average bid-to-cover {avg_btc_3:.2f}x < {btc_cfg['watch_trend']}x",
        avg_btc_3,
    )

    # --- Phase 2: Cracking ---
    add(
        jgb40 is not None and jgb_bps is not None and jgb40 > jgb_cfg["level"] and jgb_bps >= jgb_cfg["daily_move_bps"],
        2, "jgb_40y_crack",
        lambda: f"JGB 40Y {jgb40:.3f}% > {jgb_cfg['level']}% with {jgb_bps:.1f} bps daily move",
        jgb40,
    )
    add(
        ust30 is not None and ust_bps is not None and ust30 > ust_cfg["level"] and ust_bps >= ust_cfg["daily_move_bps"],
        2, "ust_30y_crack",
        lambda: f"UST 30Y {ust30:.3f}% > {ust_cfg['level']}% with {ust_bps:.1f} bps daily move",
        ust30,
    )
    recent = a.get("recent") or []
    danger_auction = next(
        (r for r in recent if _f(r.get("bid_to_cover")) is not None and r["bid_to_cover"] < btc_cfg["danger"]),
        None,
    )
    add(
        danger_auction is not None,
        2, "auction_danger",
        lambda: (
            f"{danger_auction['security_term']} auction {danger_auction['auction_date']} "
            f"bid-to-cover {danger_auction['bid_to_cover']}x < {btc_cfg['danger']}x"
        ),
        (danger_auction or {}).get("bid_to_cover"),
    )
    add(
        dxy is not None and dxy < dxy_cfg["breakdown"],
        2, "dxy_breakdown",
        lambda: f"DXY {dxy:.2f} broke {dxy_cfg['breakdown']}",
        dxy,
    )
    invert = (
        gold_pct is not None and btc_pct is not None and dxy_pct is not None
        and gold_pct > 0 and btc_pct > 0 and dxy_pct < 0
    )
    add(
        invert,
        2, "debasement_triad",
        lambda: f"Gold/BTC correlation invert: gold {gold_pct:+.2f}%, BTC {btc_pct:+.2f}%, DXY {dxy_pct:+.2f}%",
        {"gold_pct": gold_pct, "btc_pct": btc_pct, "dxy_pct": dxy_pct},
    )
    add(
        usd_jpy is not None and (usd_jpy >= yen_cfg["spike_high"] or usd_jpy <= yen_cfg["collapse_low"]),
        2, "yen_shock",
        lambda: f"USD/JPY {usd_jpy:.1f} hit spike {yen_cfg['spike_high']} / collapse {yen_cfg['collapse_low']} band",
        usd_jpy,
    )

    # --- Phase 3: Musical Chairs ---
    lookback = int(tail_cfg.get("lookback_days", 14))
    cutoff = (date.today() - timedelta(days=lookback)).isoformat()
    fresh_auctions = [r for r in recent if (r.get("auction_date") or "") >= cutoff]
    ugly_tail = next(
        (r for r in fresh_auctions if _f(r.get("tail_bps")) is not None and r["tail_bps"] > tail_cfg["action"]),
        None,
    )
    failed = next(
        (r for r in fresh_auctions if r.get("failed") or (
            _f(r.get("bid_to_cover")) is not None and r["bid_to_cover"] < btc_cfg["fail"]
        )),
        None,
    )
    add(
        ugly_tail is not None,
        3, "auction_tail",
        lambda: (
            f"{ugly_tail['security_term']} {ugly_tail['auction_date']} "
            f"tail {ugly_tail['tail_bps']} bps > {tail_cfg['action']} bps"
        ),
        (ugly_tail or {}).get("tail_bps"),
    )
    add(
        failed is not None,
        3, "auction_fail",
        lambda: (
            f"AUCTION FAILURE SIGNAL: {failed['security_term']} {failed['auction_date']} "
            f"bid-to-cover {failed.get('bid_to_cover')}x (fail < {btc_cfg['fail']}x)"
        ),
        (failed or {}).get("bid_to_cover"),
    )
    add(
        dxy is not None and dxy < dxy_cfg["crash"],
        3, "dxy_crash",
        lambda: f"DXY {dxy:.2f} through {dxy_cfg['crash']} — dollar seizure territory",
        dxy,
    )
    add(
        gold_pct is not None and abs(gold_pct) >= gold_gap_cfg["action"] and gold_pct > 0,
        3, "gold_gap",
        lambda: f"Gold gapped {gold_pct:+.2f}% in a day (threshold {gold_gap_cfg['action']}%)",
        gold_pct,
    )
    vol_ok = volume is None or volume >= vol_cfg["with_volume"]
    add(
        ratio is not None and ratio > ratio_cfg["action_break"] and vol_ok,
        3, "ratio_break",
        lambda: (
            f"BTC/gold {ratio:.1f} oz broke {ratio_cfg['action_break']} oz"
            + (f" with volume ${volume/1e9:.1f}B" if volume else "")
        ),
        ratio,
    )

    hist_ratios = [_f(r.get("btc_gold_oz")) for r in history]
    hist_ratios = [x for x in hist_ratios if x]
    ath = max(hist_ratios) if hist_ratios else ratio
    if ratio is not None and ath and ath > 0:
        distance_pct = (ath - ratio) / ath * 100.0
        add(
            distance_pct >= ratio_cfg["ath_distance_pct"],
            1, "ratio_discount",
            lambda: f"BTC/gold {ratio:.1f} oz is {distance_pct:.0f}% below series ATH {ath:.1f} oz",
            distance_pct,
        )
        add(
            ratio <= ratio_cfg["trough"],
            1, "ratio_trough",
            lambda: f"BTC/gold {ratio:.1f} oz at/below 2022-style trough {ratio_cfg['trough']}",
            ratio,
        )

    gap = _return_gap(history, days=20)
    add(
        gap is not None and abs(gap) >= widen_cfg["widen_pct"],
        1, "gold_btc_gap",
        lambda: f"20-day gold vs BTC return gap {gap:+.1f} pp (widen threshold {widen_cfg['widen_pct']}%)",
        gap,
    )
    phase = max((h["phase"] for h in hits), default=0)
    scenario = score_scenarios(snapshot, thresholds, hits)
    return {
        "phase": phase,
        "phase_name": PHASE_NAMES[phase],
        "hits": hits,
        "watch": [h for h in hits if h["phase"] == 1],
        "alert": [h for h in hits if h["phase"] == 2],
        "action": [h for h in hits if h["phase"] == 3],
        "scenario": scenario,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _return_gap(history: list[dict[str, Any]], days: int = 20) -> float | None:
    if len(history) < days + 1:
        return None
    window = history[-(days + 1) :]
    g0, g1 = _f(window[0].get("gold")), _f(window[-1].get("gold"))
    b0, b1 = _f(window[0].get("btc")), _f(window[-1].get("btc"))
    if not all([g0, g1, b0, b1]) or g0 == 0 or b0 == 0:
        return None
    gold_ret = (g1 - g0) / g0 * 100.0
    btc_ret = (b1 - b0) / b0 * 100.0
    return round(gold_ret - btc_ret, 2)


def score_scenarios(snapshot: dict[str, Any], thresholds: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristic lean — not a forecast. Weights the live tape against A/B/C/D."""
    q = snapshot.get("quotes") or {}
    keys = {h["key"] for h in hits}
    scores = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}

    jgb40 = _f(q.get("jgb_40y")) or 0
    ust30 = _f(q.get("ust_30y")) or 0
    dxy = _f(q.get("dxy")) or 100
    ratio = _f(q.get("btc_gold_oz")) or 0
    avg_btc = _f((snapshot.get("auctions") or {}).get("avg_btc_3")) or 2.5

    # Slow bleed: elevated long-end, auctions OK, DXY drifting not crashing, JGB not at 5
    if ust30 > 5.0:
        scores["A"] += 1.5
    if 4.0 <= jgb40 < 5.0:
        scores["A"] += 1.0
    if avg_btc < 2.4:
        scores["A"] += 0.8
    if 95 <= dxy < 102:
        scores["A"] += 0.6

    # Japan shock: JGB approaching 5, yen vol, auction stress
    if jgb40 >= 4.5:
        scores["B"] += 1.5
    if "usd_jpy_vol" in keys or "yen_shock" in keys:
        scores["B"] += 2.0
    if jgb40 >= 5.0:
        scores["B"] += 2.5
    if "auction_danger" in keys or avg_btc < 2.1:
        scores["B"] += 1.5
    if "jgb_40y_crack" in keys:
        scores["B"] += 2.0

    # Seizure
    if "auction_fail" in keys:
        scores["C"] += 4.0
    if "dxy_crash" in keys:
        scores["C"] += 3.0
    if "dxy_breakdown" in keys:
        scores["C"] += 1.5
    if "gold_gap" in keys:
        scores["C"] += 1.5
    if ratio >= 40:
        scores["C"] += 1.0

    # Muddle: nothing firing, gold/BTC sleepy
    if not hits:
        scores["D"] += 2.0
    if jgb40 < 4.0 and ust30 < 5.0 and dxy > 100:
        scores["D"] += 1.5
    gold = _f(q.get("gold")) or 0
    if 3000 <= gold <= 4500:
        scores["D"] += 0.8

    # Prior probabilities as a mild Bayesian nudge so a quiet tape doesn't scream Scenario C.
    prior = {"A": 0.40, "B": 0.35, "C": 0.15, "D": 0.10}
    blended = {k: scores[k] + prior[k] * 2 for k in scores}
    leader = max(blended, key=blended.get)
    return {
        "leader": leader,
        "scores": {k: round(v, 2) for k, v in blended.items()},
        "note": "Heuristic lean from the live tape, not a prediction. Priors are the 40/35/15/10 split.",
    }


def print_eval(result: dict[str, Any]) -> None:
    phase = result["phase"]
    colors = {0: "\033[32m", 1: "\033[33m", 2: "\033[31m", 3: "\033[1;31m"}
    reset = "\033[0m"
    print(f"  {colors.get(phase, '')}{result['phase_name']}{reset}")
    print("  " + "-" * 62)
    if not result["hits"]:
        print("  No thresholds breached. Stay in weekly human-check mode.")
    for bucket, title in ((3, "ACTION"), (2, "ALERT"), (1, "WATCH")):
        items = [h for h in result["hits"] if h["phase"] == bucket]
        if not items:
            continue
        print(f"  [{title}]")
        for h in items:
            print(f"    • {h['message']}")
    sc = result["scenario"]
    print()
    print(f"  Tape currently leans Scenario {sc['leader']}  scores={sc['scores']}")
    print()


def notify(result: dict[str, Any], voice: bool = False, hook: str | None = None) -> None:
    if result["phase"] < 2:
        return
    title = "Debt Tracker"
    body = result["phase_name"] + " — " + (result["hits"][0]["message"] if result["hits"] else "")
    body = body[:180]
    system = platform.system()
    if system == "Darwin":
        script = f'display notification {json.dumps(body)} with title {json.dumps(title)} sound name "Sosumi"'
        subprocess.run(["osascript", "-e", script], check=False)
        if voice:
            spoken = "Phase 2 alert." if result["phase"] == 2 else "Phase 3. Musical chairs."
            subprocess.run(["say", spoken], check=False)
    elif system == "Linux":
        subprocess.run(["notify-send", title, body], check=False)
    if hook:
        proc = subprocess.run(hook, shell=True, input=json.dumps(result).encode(), check=False)
        if proc.returncode:
            print(f"  hook exited {proc.returncode}", file=sys.stderr)


def write_dashboard(snapshot: dict[str, Any], result: dict[str, Any], history: list[dict[str, Any]]) -> None:
    scenarios = load_json(SCENARIOS_PATH)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = (
        template.replace("__SNAPSHOT__", json.dumps(snapshot))
        .replace("__EVAL__", json.dumps(result))
        .replace("__HISTORY__", json.dumps(history))
        .replace("__SCENARIOS__", json.dumps(scenarios))
        .replace("__GENERATED__", snapshot.get("pulled_at", ""))
    )
    DASHBOARD_PATH.write_text(html, encoding="utf-8")


def patch_history_phase(phase: int) -> None:
    """Stamp the latest CSV row with the evaluated phase."""
    import csv
    from tracker import HISTORY_FIELDS

    if not HISTORY_PATH.exists():
        return
    with HISTORY_PATH.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return
    rows[-1]["phase"] = str(phase)
    with HISTORY_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_alerts(notify_on: bool = False, voice: bool = False, hook: str | None = None) -> int:
    if not SNAPSHOT_PATH.exists():
        print("No last_run.json — run tracker.py first.", file=sys.stderr)
        return 2
    snapshot = load_json(SNAPSHOT_PATH)
    thresholds = load_json(THRESHOLDS_PATH)
    history = load_history()
    result = evaluate(snapshot, thresholds, history)
    print_eval(result)
    ALERTS_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    patch_history_phase(result["phase"])
    write_dashboard(snapshot, result, history)
    print(f"  Wrote {DASHBOARD_PATH.name}  {ALERTS_PATH.name}  {HISTORY_PATH.name}")
    if notify_on or voice or hook:
        notify(result, voice=voice, hook=hook)
    # Cron-friendly: exit 2 on action, 1 on alert, 0 otherwise.
    if result["phase"] >= 3:
        return 2
    if result["phase"] >= 2:
        return 1
    return 0


def _self_test() -> int:
    thresholds = load_json(THRESHOLDS_PATH)
    base = {
        "quotes": {
            "jgb_40y": 3.2, "ust_30y": 4.4, "usd_jpy": 155, "dxy": 104,
            "gold": 3400, "btc": 70000, "btc_gold_oz": 20.6, "btc_volume": 3e10,
        },
        "changes": {
            "jgb_40y_bps": 1, "ust_30y_bps": 2, "gold_pct": 0.2, "btc_pct": -0.4, "dxy_pct": 0.1,
        },
        "auctions": {"avg_btc_3": 2.5, "recent": [], "latest_30y": {}, "latest_10y": {}},
    }
    r0 = evaluate(base, thresholds, [])
    assert r0["phase"] == 0, r0

    watch = json.loads(json.dumps(base))
    watch["quotes"]["ust_30y"] = 5.2
    r1 = evaluate(watch, thresholds, [])
    assert r1["phase"] == 1, r1

    crack = json.loads(json.dumps(base))
    crack["quotes"]["jgb_40y"] = 5.12
    crack["changes"]["jgb_40y_bps"] = 22
    r2 = evaluate(crack, thresholds, [])
    assert r2["phase"] == 2, r2

    seize = json.loads(json.dumps(base))
    seize["quotes"]["dxy"] = 89.4
    r3 = evaluate(seize, thresholds, [])
    assert r3["phase"] == 3, r3

    fail = json.loads(json.dumps(base))
    fail["auctions"]["recent"] = [{
        "auction_date": date.today().isoformat(),
        "security_term": "30-Year",
        "bid_to_cover": 1.65,
        "tail_bps": 12,
        "failed": True,
    }]
    r4 = evaluate(fail, thresholds, [])
    assert r4["phase"] == 3, r4
    print("self-test ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate thresholds and refresh dashboard.html")
    parser.add_argument("--notify", action="store_true")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--hook", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    return run_alerts(notify_on=args.notify, voice=args.voice, hook=args.hook or None)


if __name__ == "__main__":
    sys.exit(main())
