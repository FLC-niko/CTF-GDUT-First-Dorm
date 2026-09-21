"""Integration test for tiered scheduling, triage, state persistence, and racing."""

from __future__ import annotations

from pathlib import Path

from backend.challenge_manager import ChallengeManager, ChallengeStatus
from backend.persistence import StatePersistence
from backend.prompts import ChallengeMeta
from backend.scheduler import TieredModelConfig, TieredScheduler
from backend.triage import ChallengeTriager


def test_end_to_end_tiered_dispatch_and_escalation(tmp_path: Path) -> None:
    state_file = tmp_path / "comp_state.json"
    persistence = StatePersistence(state_file)
    manager = ChallengeManager(persistence=persistence, max_concurrent_challenges=3)
    triager = ChallengeTriager()

    config = TieredModelConfig(
        fast_models=("codex/gpt-5.4-mini",),
        expert_models=("codex/gpt-5.4",),
        racing_models=("codex/gpt-5.4", "cpa-responses/gemini-2.5-pro", "go-messages/deepseek-r1"),
    )
    scheduler = TieredScheduler(config)

    # 1. Simulate 5 challenges registered
    challenges_data = [
        ("web_easy", "web", 100, []),
        ("misc_forensics", "misc", 150, ["traffic.pcap"]),
        ("crypto_rsa", "crypto", 300, ["task.sage"]),
        ("pwn_bof", "pwn", 200, ["vuln"]),
        ("rev_hard", "reverse", 500, ["crackme"]),
    ]

    for name, cat, val, files in challenges_data:
        chal_dir = tmp_path / name
        chal_dir.mkdir(parents=True, exist_ok=True)
        distfiles_dir = chal_dir / "distfiles"
        distfiles_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            (distfiles_dir / f).write_text("data", encoding="utf-8")

        meta = ChallengeMeta(name=name, category=cat, value=val)
        manager.register_challenge(chal_dir, meta)
        triage_report = triager.heuristic_triage(meta, distfile_names=files)
        manager.record_triage(name, triage_report)

    # 2. Verify triage results and tier assignments
    assert manager.challenges["web_easy"].tier == "fast"
    assert manager.challenges["misc_forensics"].tier == "fast"
    assert manager.challenges["crypto_rsa"].tier == "expert"  # .sage elevated to expert
    assert manager.challenges["rev_hard"].tier == "expert"    # 500 points elevated to expert

    # 3. Fast solver model dispatch
    fast_models = scheduler.select_models(manager.challenges["web_easy"])
    assert fast_models == ["codex/gpt-5.4-mini"]

    # 4. Expert solver model dispatch
    expert_models = scheduler.select_models(manager.challenges["rev_hard"])
    assert expert_models == ["codex/gpt-5.4"]

    # 5. Escalate web_easy from fast -> expert -> racing on repeated failures
    manager.record_failure("web_easy", "waf blocking")
    assert manager.challenges["web_easy"].tier == "expert"
    assert scheduler.select_models(manager.challenges["web_easy"]) == ["codex/gpt-5.4"]

    manager.record_failure("web_easy", "complex filter")
    assert manager.challenges["web_easy"].tier == "racing"
    racing_models = scheduler.select_models(manager.challenges["web_easy"])
    assert len(racing_models) == 3
    assert "go-messages/deepseek-r1" in racing_models

    # 6. Flag candidate found by racing solver
    manager.record_candidate_flag("web_easy", "flag{sqli_bypass_win}", "go-messages/deepseek-r1")
    assert manager.challenges["web_easy"].status is ChallengeStatus.SOLVED
    assert manager.challenges["web_easy"].confirmed_flag is None

    # 7. Platform confirms flag
    manager.record_confirmed_flag("web_easy", "flag{sqli_bypass_win}")
    assert manager.challenges["web_easy"].status is ChallengeStatus.CONFIRMED

    # 8. Recovery test: reload manager from persistence file
    manager_recovered = ChallengeManager(persistence=persistence)
    assert len(manager_recovered.challenges) == 5
    assert manager_recovered.challenges["web_easy"].status is ChallengeStatus.CONFIRMED
    assert manager_recovered.challenges["web_easy"].candidate_flag == "flag{sqli_bypass_win}"
    assert manager_recovered.challenges["crypto_rsa"].tier == "expert"
