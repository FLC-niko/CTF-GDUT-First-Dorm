"""Render a benchmark report from externally collected run records.

This command does not execute solvers and must not be described as an empirical
benchmark run. It deliberately requires an input file so generated fixtures can
never be mistaken for live provider or historical CTF evidence.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from backend.benchmark import BenchmarkRunner, BenchmarkSuiteResult, BenchmarkTaskResult


def _load_tasks(path: Path) -> list[BenchmarkTaskResult]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("provenance") != "measured":
        raise ValueError("input must declare provenance='measured'")
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("input must contain a non-empty tasks list")

    fields = BenchmarkTaskResult.__dataclass_fields__
    return [
        BenchmarkTaskResult(**{key: value for key, value in task.items() if key in fields})
        for task in raw_tasks
        if isinstance(task, dict)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a report from measured benchmark task records."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark_reports"))
    parser.add_argument("--report-name", default="benchmark_report")
    args = parser.parse_args()

    tasks = _load_tasks(args.input)
    if not tasks:
        raise ValueError("input did not contain any valid task records")
    suite = BenchmarkSuiteResult(timestamp=time.time(), tasks=tasks)
    report = BenchmarkRunner(output_dir=args.output_dir).record_run(
        suite,
        report_name=args.report_name,
    )
    print(f"Benchmark report written to {report}")


if __name__ == "__main__":
    main()
