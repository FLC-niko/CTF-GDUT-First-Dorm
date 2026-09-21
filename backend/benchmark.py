"""CTF Model Evaluation and Benchmark Engine.

Runs reproducible benchmark runs against standardized challenge suites,
measuring Time-to-Flag, solve rate, tool accuracy, token cost, and marginal
racing coverage. Emits structured JSON metrics and Markdown reports.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.prompts import ChallengeMeta

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkTaskResult:
    challenge_name: str
    category: str
    model_spec: str
    mode: str  # "fast", "expert", "racing"
    solved: bool
    time_to_flag_s: float
    flag: str | None = None
    tool_calls_count: int = 0
    tool_success_count: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: str = ""

    @property
    def tool_accuracy(self) -> float:
        if self.tool_calls_count == 0:
            return 1.0
        return self.tool_success_count / self.tool_calls_count

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tool_accuracy"] = round(self.tool_accuracy, 3)
        return d


@dataclass
class ModelPerformanceSummary:
    model_spec: str
    mode: str
    total_challenges: int
    solved_count: int
    solve_rate: float
    avg_time_to_flag_s: float
    avg_tool_accuracy: float
    total_tokens: int
    total_cost_usd: float


@dataclass
class BenchmarkSuiteResult:
    timestamp: float
    tasks: list[BenchmarkTaskResult] = field(default_factory=list)
    summary_by_model: dict[str, ModelPerformanceSummary] = field(default_factory=dict)
    marginal_racing_coverage: float = 0.0

    def compute_summary(self) -> None:
        grouped: dict[tuple[str, str], list[BenchmarkTaskResult]] = {}
        for t in self.tasks:
            key = (t.model_spec, t.mode)
            grouped.setdefault(key, []).append(t)

        self.summary_by_model.clear()
        expert_solved: set[str] = set()
        racing_solved: set[str] = set()

        for (m, mode), results in grouped.items():
            count = len(results)
            solved_res = [r for r in results if r.solved]
            solved_count = len(solved_res)
            solve_rate = solved_count / count if count > 0 else 0.0
            avg_time = (
                sum(r.time_to_flag_s for r in solved_res) / solved_count
                if solved_count > 0
                else 0.0
            )
            avg_acc = sum(r.tool_accuracy for r in results) / count if count > 0 else 0.0
            total_tok = sum(r.tokens_used for r in results)
            total_cost = sum(r.cost_usd for r in results)

            label = f"{m} [{mode}]"
            self.summary_by_model[label] = ModelPerformanceSummary(
                model_spec=m,
                mode=mode,
                total_challenges=count,
                solved_count=solved_count,
                solve_rate=round(solve_rate, 3),
                avg_time_to_flag_s=round(avg_time, 2),
                avg_tool_accuracy=round(avg_acc, 3),
                total_tokens=total_tok,
                total_cost_usd=round(total_cost, 4),
            )

            if mode == "expert":
                expert_solved.update(r.challenge_name for r in solved_res)
            elif mode == "racing":
                racing_solved.update(r.challenge_name for r in solved_res)

        if expert_solved or racing_solved:
            union = expert_solved | racing_solved
            extra_by_racing = len(racing_solved - expert_solved)
            self.marginal_racing_coverage = extra_by_racing / len(union) if union else 0.0

    def to_markdown(self) -> str:
        self.compute_summary()
        lines = [
            "# CTF Benchmark Performance Report",
            f"\n> Generated at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.timestamp))}\n",
            "## 1. Summary by Model & Mode\n",
            "| Model & Mode | Total | Solved | Solve Rate | Avg Time-to-Flag (s) | Tool Accuracy | Total Tokens |",
            "|--------------|-------|--------|------------|----------------------|---------------|--------------|",
        ]
        for label, s in self.summary_by_model.items():
            lines.append(
                f"| `{label}` | {s.total_challenges} | {s.solved_count} | {s.solve_rate * 100:.1f}% | {s.avg_time_to_flag_s}s | {s.avg_tool_accuracy * 100:.1f}% | {s.total_tokens} |"
            )

        lines.extend([
            f"\n**Marginal Racing Coverage Benefit**: {self.marginal_racing_coverage * 100:.1f}%\n",
            "## 2. Recommended Solver Role Matrix\n",
            "- **Fast Solver (Warmup/初筛)**: Lightweight small models (`codex/gpt-5.4-mini` / `go-chat/qwen-2.5-coder-7b`), prioritizing low token usage and high tool invocation speed.",
            "- **Expert Solver (Deep Reasoning/攻坚)**: Strong reasoning models (`codex/gpt-5.4` / `go-messages/deepseek-r1`), handling complex multi-step exploits.",
            "- **Racing Solver (Cross-Family/瓶颈突破)**: Combining different model families (`Codex GPT` + `CPA Gemini` + `Go DeepSeek`), exploring orthogonal attack vectors when Expert stalls.",
            "\n## 3. Individual Challenge Results\n",
            "| Challenge | Category | Model | Mode | Solved | Time (s) | Tool Acc |",
            "|-----------|----------|-------|------|--------|----------|----------|",
        ])
        for t in self.tasks:
            status = "✅" if t.solved else "❌"
            lines.append(
                f"| {t.challenge_name} | {t.category} | `{t.model_spec}` | {t.mode} | {status} | {t.time_to_flag_s:.1f}s | {t.tool_accuracy * 100:.1f}% |"
            )

        return "\n".join(lines)


class BenchmarkRunner:
    """Executes benchmark evaluations."""

    def __init__(self, output_dir: str | Path = "benchmark_reports") -> None:
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def record_run(self, result: BenchmarkSuiteResult, report_name: str = "benchmark_report") -> Path:
        result.compute_summary()
        json_path = self.output_dir / f"{report_name}.json"
        md_path = self.output_dir / f"{report_name}.md"

        data = {
            "timestamp": result.timestamp,
            "tasks": [t.to_dict() for t in result.tasks],
            "summary": {k: asdict(v) for k, v in result.summary_by_model.items()},
            "marginal_racing_coverage": round(result.marginal_racing_coverage, 3),
        }
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(result.to_markdown(), encoding="utf-8")
        logger.info("Saved benchmark report to %s and %s", json_path, md_path)
        return md_path

