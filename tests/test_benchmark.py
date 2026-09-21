"""Tests for the BenchmarkRunner and BenchmarkSuiteResult reporting."""

from __future__ import annotations

import json
from pathlib import Path

from backend.benchmark import (
    BenchmarkRunner,
    BenchmarkSuiteResult,
    BenchmarkTaskResult,
)


def test_benchmark_runner_and_report_generation(tmp_path: Path) -> None:
    runner = BenchmarkRunner(output_dir=tmp_path / "reports")

    # Create synthetic benchmark task results representing a 5-challenge run
    tasks = [
        # Fast model results
        BenchmarkTaskResult(
            challenge_name="web_jwt_bypass",
            category="web",
            model_spec="codex/gpt-5.4-mini",
            mode="fast",
            solved=True,
            time_to_flag_s=25.4,
            flag="flag{admin_bypass}",
            tool_calls_count=4,
            tool_success_count=4,
            tokens_used=1200,
            cost_usd=0.002,
        ),
        BenchmarkTaskResult(
            challenge_name="misc_stego_flag",
            category="misc",
            model_spec="codex/gpt-5.4-mini",
            mode="fast",
            solved=True,
            time_to_flag_s=18.2,
            flag="flag{exif_metadata_found}",
            tool_calls_count=3,
            tool_success_count=3,
            tokens_used=950,
            cost_usd=0.0015,
        ),
        BenchmarkTaskResult(
            challenge_name="crypto_affine",
            category="crypto",
            model_spec="codex/gpt-5.4-mini",
            mode="fast",
            solved=False,
            time_to_flag_s=60.0,
            tool_calls_count=5,
            tool_success_count=3,
            tokens_used=3500,
            cost_usd=0.005,
            error="Modular inverse failed",
        ),
        # Expert model results
        BenchmarkTaskResult(
            challenge_name="crypto_affine",
            category="crypto",
            model_spec="codex/gpt-5.4",
            mode="expert",
            solved=True,
            time_to_flag_s=42.1,
            flag="flag{affinecipher_solved}",
            tool_calls_count=6,
            tool_success_count=6,
            tokens_used=4200,
            cost_usd=0.015,
        ),
        BenchmarkTaskResult(
            challenge_name="pwn_ret2text",
            category="pwn",
            model_spec="codex/gpt-5.4",
            mode="expert",
            solved=False,
            time_to_flag_s=120.0,
            tool_calls_count=8,
            tool_success_count=5,
            tokens_used=7800,
            cost_usd=0.03,
            error="Payload offset mismatched",
        ),
        # Racing mode on pwn_ret2text
        BenchmarkTaskResult(
            challenge_name="pwn_ret2text",
            category="pwn",
            model_spec="go-messages/deepseek-r1",
            mode="racing",
            solved=True,
            time_to_flag_s=68.5,
            flag="flag{ret2win_pwned}",
            tool_calls_count=7,
            tool_success_count=7,
            tokens_used=6100,
            cost_usd=0.012,
        ),
    ]

    suite = BenchmarkSuiteResult(timestamp=1700000000.0, tasks=tasks)
    report_file = runner.record_run(suite, report_name="ctf_standard_benchmark")

    assert report_file.is_file()
    md_content = report_file.read_text(encoding="utf-8")
    assert "# CTF Benchmark Performance Report" in md_content
    assert "codex/gpt-5.4-mini [fast]" in md_content
    assert "Marginal Racing Coverage Benefit" in md_content

    json_file = tmp_path / "reports" / "ctf_standard_benchmark.json"
    assert json_file.is_file()
    json_data = json.loads(json_file.read_text(encoding="utf-8"))
    assert "summary" in json_data
    assert json_data["marginal_racing_coverage"] > 0

