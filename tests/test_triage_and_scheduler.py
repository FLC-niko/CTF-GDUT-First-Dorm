"""Tests for Triage and TieredScheduler logic."""

from __future__ import annotations

from backend.challenge_manager import ChallengeEntry
from backend.prompts import ChallengeMeta
from backend.scheduler import TieredModelConfig, TieredScheduler
from backend.triage import ChallengeTriager


def test_heuristic_triage_categories() -> None:
    triager = ChallengeTriager()

    pwn_meta = ChallengeMeta(name="pwn_heap", category="pwn", tags=["heap", "uaf"])
    report = triager.heuristic_triage(pwn_meta)
    assert report.category == "pwn"
    assert report.suggested_tier == "expert"
    assert "pwntools" in report.required_tools

    web_meta = ChallengeMeta(name="web_sqli", category="web", value=100)
    report_web = triager.heuristic_triage(web_meta)
    assert report_web.category == "web"
    assert report_web.suggested_tier == "fast"

    crypto_meta = ChallengeMeta(name="lattice_rsa", category="crypto", tags=["lattice"])
    report_crypto = triager.heuristic_triage(crypto_meta, distfile_names=["task.sage"])
    assert report_crypto.category == "crypto"
    assert report_crypto.suggested_tier == "expert"
    assert "sage" in report_crypto.required_tools


def test_tiered_scheduler_dispatch() -> None:
    config = TieredModelConfig(
        fast_models=("codex/gpt-5.4-mini",),
        expert_models=("codex/gpt-5.4",),
        racing_models=("codex/gpt-5.4", "cpa-responses/gemini-2.5-pro", "go-messages/deepseek-r1"),
        fast_timeout_s=120,
        expert_timeout_s=600,
        racing_timeout_s=1200,
    )
    scheduler = TieredScheduler(config)

    meta = ChallengeMeta(name="demo", category="misc")
    entry = ChallengeEntry(name="demo", challenge_dir="/tmp", meta=meta)

    # 1. Fast tier
    entry.tier = "fast"
    assert scheduler.select_models(entry) == ["codex/gpt-5.4-mini"]
    assert scheduler.get_timeout_s(entry) == 120

    # 2. Expert tier
    entry.tier = "expert"
    assert scheduler.select_models(entry) == ["codex/gpt-5.4"]
    assert scheduler.get_timeout_s(entry) == 600

    # 3. Racing tier
    entry.tier = "racing"
    selected = scheduler.select_models(entry)
    assert len(selected) == 3
    assert "cpa-responses/gemini-2.5-pro" in selected
    assert "go-messages/deepseek-r1" in selected
    assert scheduler.get_timeout_s(entry) == 1200
