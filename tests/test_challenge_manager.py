"""Unit and integration tests for ChallengeManager and state persistence."""

from __future__ import annotations

from pathlib import Path

from backend.challenge_manager import ChallengeManager, ChallengeStatus
from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.deps import CoordinatorDeps
from backend.persistence import StatePersistence
from backend.prompts import ChallengeMeta
from backend.triage import TriageReport


def test_state_persistence_atomic_write_and_read(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    persistence = StatePersistence(state_file)

    assert not persistence.exists()
    assert persistence.load() is None

    sample_data = {
        "version": 1,
        "team": "FLC",
        "api_key": "secret-key-12345",  # should be redacted
        "challenges": {"pwn1": {"status": "pending", "value": 100}},
    }
    persistence.save(sample_data)

    assert persistence.exists()
    loaded = persistence.load()
    assert loaded is not None
    assert loaded["version"] == 1
    assert loaded["team"] == "FLC"
    assert loaded["api_key"] == "<redacted>"
    assert loaded["challenges"]["pwn1"]["value"] == 100


def test_challenge_manager_lifecycle_and_recovery(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    persistence = StatePersistence(state_file)
    manager = ChallengeManager(persistence=persistence, max_concurrent_challenges=2)

    # 1. Register challenge
    chal_dir = tmp_path / "pwn-chal"
    chal_dir.mkdir()
    meta = ChallengeMeta(
        name="ret2text",
        category="pwn",
        value=200,
        description="Stack challenge",
        tags=["stack"],
        connection_info="nc challenge.example 31337",
        platform="ctfd",
        platform_url="https://ctf.example",
        event_id=7,
        platform_challenge_id=11,
        requires_env_start=True,
    )
    entry = manager.register_challenge(chal_dir, meta)
    assert entry.status is ChallengeStatus.PENDING

    # 2. Record Triage
    triage = TriageReport(
        challenge_name="ret2text",
        category="pwn",
        complexity_score=2,
        suggested_tier="fast",
        technical_routes=("buffer overflow",),
        summary="easy pwn",
    )
    manager.record_triage("ret2text", triage)
    assert entry.status is ChallengeStatus.TRIAGED
    assert entry.tier == "fast"

    # 3. Simulate solving failure and tier escalation
    manager.record_failure("ret2text", "timeout")
    assert entry.attempts == 1
    assert entry.tier == "expert"  # upgraded to expert
    assert entry.status is ChallengeStatus.TRIAGED

    manager.record_failure("ret2text", "second timeout")
    assert entry.attempts == 2
    assert entry.tier == "racing"  # upgraded to racing

    # 4. Record Candidate Flag (SOLVED, not CONFIRMED)
    manager.record_candidate_flag("ret2text", "flag{candidate_test}", "codex/gpt-5.4")
    assert entry.status is ChallengeStatus.SOLVED
    assert entry.candidate_flag == "flag{candidate_test}"
    assert entry.confirmed_flag is None

    # 5. Record Platform Confirmation
    manager.record_confirmed_flag("ret2text", "flag{candidate_test}")
    assert entry.status is ChallengeStatus.CONFIRMED
    assert entry.confirmed_flag == "flag{candidate_test}"

    # 6. Verify crash recovery in a new manager instance
    manager2 = ChallengeManager(persistence=persistence, max_concurrent_challenges=2)
    assert "ret2text" in manager2.challenges
    restored = manager2.challenges["ret2text"]
    assert restored.status is ChallengeStatus.CONFIRMED
    assert restored.confirmed_flag == "flag{candidate_test}"
    assert restored.tier == "racing"
    assert restored.meta == meta


def test_coordinator_dependencies_do_not_share_implicit_repository_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, competition_state_file="")
    first = CoordinatorDeps(
        ctfd=object(),  # type: ignore[arg-type]
        cost_tracker=CostTracker(),
        settings=settings,
        model_specs=[],
    )
    first.challenge_manager.register_challenge(
        tmp_path / "first",
        ChallengeMeta(name="first"),
    )

    second = CoordinatorDeps(
        ctfd=object(),  # type: ignore[arg-type]
        cost_tracker=CostTracker(),
        settings=Settings(_env_file=None, competition_state_file=""),
        model_specs=[],
    )

    assert second.challenge_manager.challenges == {}
    assert not (tmp_path / "competition_state.json").exists()
