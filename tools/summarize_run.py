from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Optional, Tuple


def _find_latest_run(root: Path) -> Optional[Path]:
    candidates = list(root.rglob("run_*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _mean(values: Iterable[float]) -> Optional[float]:
    items = [v for v in values if v is not None]
    if not items:
        return None
    return sum(items) / len(items)


def _collect_metric(records: Iterable[dict], key: str) -> Optional[float]:
    values = []
    for rec in records:
        val = rec.get(key)
        if isinstance(val, (int, float)):
            values.append(float(val))
    return _mean(values)


def _format(val: Optional[float]) -> str:
    if val is None:
        return "NA"
    return f"{val:.3f}"


def _load_records(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _make_table(
    metric_count: int,
    infer_fps_avg: Optional[float],
    display_fps_avg: Optional[float],
    rt_ratio_avg: Optional[float],
    target_ratio_avg: Optional[float],
) -> str:
    headers = [
        "metric_count",
        "infer_fps_avg",
        "display_fps_avg",
        "rt_ratio_avg",
        "target_ratio_avg",
    ]
    values = [
        str(metric_count),
        _format(infer_fps_avg),
        _format(display_fps_avg),
        _format(rt_ratio_avg),
        _format(target_ratio_avg),
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
        "| " + " | ".join(values) + " |",
    ]
    return "\n".join(lines)


def summarize(path: Path, warmup_s: float) -> Tuple[str, dict]:
    records = _load_records(path)
    if warmup_s is not None and warmup_s > 0:
        cutoff = warmup_s * 1000.0
        records = [rec for rec in records if (rec.get("timestamp_ms") or 0.0) >= cutoff]
    metric_count = len(records)
    infer_fps_avg = _collect_metric(records, "fps")
    display_fps_avg = _collect_metric(records, "display_fps")
    rt_ratio_avg = _collect_metric(records, "rt_ratio")
    target_ratio_avg = _collect_metric(records, "target_ratio")
    table = _make_table(
        metric_count,
        infer_fps_avg,
        display_fps_avg,
        rt_ratio_avg,
        target_ratio_avg,
    )
    metrics = {
        "metric_count": metric_count,
        "infer_fps_avg": infer_fps_avg,
        "display_fps_avg": display_fps_avg,
        "rt_ratio_avg": rt_ratio_avg,
        "target_ratio_avg": target_ratio_avg,
    }
    return table, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Root to search for run_*.jsonl")
    parser.add_argument("--run", default=None, help="Explicit run_*.jsonl path")
    parser.add_argument("--write-results", action="store_true", help="Write results.md next to run file")
    parser.add_argument("--warmup-s", type=float, default=0.5, help="Warmup seconds to skip")
    args = parser.parse_args()

    run_path = Path(args.run) if args.run else _find_latest_run(Path(args.root))
    if run_path is None or not run_path.exists():
        print("No run_*.jsonl found.")
        return 1

    table, _ = summarize(run_path, args.warmup_s)
    print(table)

    if args.write_results:
        results_path = run_path.parent / "results.md"
        results_path.write_text(table + "\n", encoding="utf-8")
        print(f"Wrote: {results_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
