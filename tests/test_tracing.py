from __future__ import annotations

import json
from pathlib import Path

from backend.agents.solver import _build_handoff_observation
from backend.tracing import SolverTracer


def test_solver_trace_redacts_flags_credentials_and_submit_arguments(tmp_path: Path) -> None:
    tracer = SolverTracer("challenge", "model", log_dir=str(tmp_path))
    tracer.tool_call("submit_flag", {"flag": "FLAG{trace-canary}"}, 1)
    tracer.tool_result("bash", "found CTF{result-canary} with sk-secretcanary", 2)
    tracer.event(
        "finish",
        flag="GDUT{event-canary}",
        token="token-canary",
        detail="Authorization: Bearer abcdefghijklmnop",
    )
    tracer.close()

    content = Path(tracer.path).read_text(encoding="utf-8")
    events = [json.loads(line) for line in content.splitlines()]

    assert "trace-canary" not in content
    assert "result-canary" not in content
    assert "event-canary" not in content
    assert "secretcanary" not in content
    assert "abcdefghijklmnop" not in content
    assert events[0]["args"] == "<redacted>"
    assert events[2]["flag"] == "<redacted>"
    assert events[2]["token"] == "<redacted>"


def test_handoff_observation_is_bounded_labeled_and_redacted() -> None:
    observation = _build_handoff_observation(
        "bash",
        "response CTF{handoff-canary} token sk-handoffsecret " + ("x" * 1200),
    )

    assert observation.startswith("Unverified tool observation from `bash`:")
    assert "handoff-canary" not in observation
    assert "handoffsecret" not in observation
    assert len(observation) < 900


def test_handoff_observation_skips_coordination_and_submission_tools() -> None:
    assert _build_handoff_observation("notify_coordinator", "message") == ""
    assert _build_handoff_observation("check_findings", "message") == ""
    assert _build_handoff_observation("submit_flag", "CTF{candidate}") == ""
