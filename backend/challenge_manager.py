"""Challenge manager and lifecycle state machine.

Coordinates challenge queues, prioritization, triage status, solver tier assignment,
and candidate-vs-confirmed flag transitions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.persistence import StatePersistence
from backend.prompts import ChallengeMeta
from backend.triage import SolverTier, TriageReport

logger = logging.getLogger(__name__)


class ChallengeStatus(StrEnum):
    PENDING = "pending"          # Discovered or imported, waiting for triage
    TRIAGED = "triaged"          # Triage complete, ready to be dispatched
    SOLVING = "solving"          # Actively being solved by one or more agents
    PAUSED = "paused"            # Temporarily suspended (e.g. rate limit cooldown)
    SOLVED = "solved"            # Candidate flag obtained, pending platform confirmation
    CONFIRMED = "confirmed"      # Flag verified and accepted by the competition platform
    FAILED = "failed"            # Max attempts exhausted, or gave up
    SKIPPED = "skipped"          # Explicitly skipped by operator or policy rule


@dataclass
class ChallengeEntry:
    name: str
    challenge_dir: str
    meta: ChallengeMeta
    status: ChallengeStatus = ChallengeStatus.PENDING
    tier: SolverTier = "fast"
    triage_report: TriageReport | None = None
    priority: float = 100.0
    attempts: int = 0
    max_attempts: int = 3
    active_solvers: list[str] = field(default_factory=list)
    candidate_flag: str | None = None
    confirmed_flag: str | None = None
    winner_model: str = ""
    discovered_at: float = field(default_factory=time.time)
    last_state_change: float = field(default_factory=time.time)
    cost_usd: float = 0.0
    total_tokens: int = 0
    notes: str = ""

    def transition_to(self, new_status: ChallengeStatus, reason: str = "") -> None:
        old_status = self.status
        self.status = new_status
        self.last_state_change = time.time()
        if reason:
            self.notes = f"[{new_status.value}] {reason}"
        logger.info("Challenge '%s': %s -> %s (reason: %s)", self.name, old_status, new_status, reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "challenge_dir": self.challenge_dir,
            "category": self.meta.category,
            "status": self.status.value,
            "tier": self.tier,
            "triage_report": self.triage_report.to_dict() if self.triage_report else None,
            "priority": self.priority,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "active_solvers": list(self.active_solvers),
            "candidate_flag": self.candidate_flag,
            "confirmed_flag": self.confirmed_flag,
            "winner_model": self.winner_model,
            "discovered_at": self.discovered_at,
            "last_state_change": self.last_state_change,
            "cost_usd": self.cost_usd,
            "total_tokens": self.total_tokens,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChallengeEntry:
        meta = ChallengeMeta(
            name=data["name"],
            category=data.get("category", ""),
        )
        triage = TriageReport.from_dict(data["triage_report"]) if data.get("triage_report") else None
        return cls(
            name=data["name"],
            challenge_dir=data.get("challenge_dir", ""),
            meta=meta,
            status=ChallengeStatus(data.get("status", "pending")),
            tier=data.get("tier", "fast"),
            triage_report=triage,
            priority=float(data.get("priority", 100.0)),
            attempts=int(data.get("attempts", 0)),
            max_attempts=int(data.get("max_attempts", 3)),
            active_solvers=list(data.get("active_solvers", [])),
            candidate_flag=data.get("candidate_flag"),
            confirmed_flag=data.get("confirmed_flag"),
            winner_model=data.get("winner_model", ""),
            discovered_at=float(data.get("discovered_at", time.time())),
            last_state_change=float(data.get("last_state_change", time.time())),
            cost_usd=float(data.get("cost_usd", 0.0)),
            total_tokens=int(data.get("total_tokens", 0)),
            notes=str(data.get("notes", "")),
        )


class ChallengeManager:
    """Manages the full lifecycle of challenges in a competition."""

    def __init__(
        self,
        persistence: StatePersistence | None = None,
        max_concurrent_challenges: int = 3,
    ) -> None:
        self.challenges: dict[str, ChallengeEntry] = {}
        self.persistence = persistence
        self.max_concurrent_challenges = max_concurrent_challenges
        self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        if not self.persistence:
            return
        data = self.persistence.load()
        if not data or "challenges" not in data:
            return
        for name, item in data["challenges"].items():
            try:
                entry = ChallengeEntry.from_dict(item)
                # If a challenge was in 'solving' state when previous process died, reset to triaged/pending
                if entry.status is ChallengeStatus.SOLVING:
                    entry.status = ChallengeStatus.TRIAGED
                    entry.active_solvers.clear()
                    entry.notes = "Reset to triaged from ungraceful shutdown"
                self.challenges[name] = entry
            except Exception as exc:
                logger.warning("Failed to restore challenge '%s': %s", name, exc)
        logger.info("Restored %d challenges from persistence", len(self.challenges))

    def save_state(self) -> None:
        if not self.persistence:
            return
        serialized = {
            "version": 1,
            "updated_at": time.time(),
            "challenges": {k: v.to_dict() for k, v in self.challenges.items()},
        }
        self.persistence.save(serialized)

    def register_challenge(self, challenge_dir: str | Path, meta: ChallengeMeta) -> ChallengeEntry:
        """Register a new challenge or return existing entry."""
        if meta.name in self.challenges:
            return self.challenges[meta.name]

        entry = ChallengeEntry(
            name=meta.name,
            challenge_dir=str(Path(challenge_dir).resolve()),
            meta=meta,
            status=ChallengeStatus.PENDING,
            priority=float(meta.value or 100.0),
        )
        self.challenges[meta.name] = entry
        self.save_state()
        return entry

    def record_triage(self, challenge_name: str, report: TriageReport) -> None:
        entry = self.challenges.get(challenge_name)
        if not entry:
            raise KeyError(f"Challenge '{challenge_name}' not registered")
        entry.triage_report = report
        entry.tier = report.suggested_tier
        # Higher complexity challenges with low current solved count receive higher priority
        complexity_bonus = (5 - report.complexity_score) * 10  # fast easy challenges get quick solve priority
        entry.priority = float((entry.meta.value or 100.0) + complexity_bonus)
        entry.transition_to(ChallengeStatus.TRIAGED, f"Triage complete (score={report.complexity_score})")
        self.save_state()

    def record_candidate_flag(self, challenge_name: str, flag: str, model_spec: str) -> None:
        """Record candidate flag without submitting; sets status to SOLVED."""
        entry = self.challenges.get(challenge_name)
        if not entry:
            return
        entry.candidate_flag = flag
        entry.winner_model = model_spec
        entry.transition_to(ChallengeStatus.SOLVED, f"Candidate flag found by {model_spec}")
        self.save_state()

    def record_confirmed_flag(self, challenge_name: str, flag: str) -> None:
        """Record platform confirmation of a flag; sets status to CONFIRMED."""
        entry = self.challenges.get(challenge_name)
        if not entry:
            return
        entry.confirmed_flag = flag
        entry.transition_to(ChallengeStatus.CONFIRMED, "Platform accepted flag")
        self.save_state()

    def record_failure(self, challenge_name: str, reason: str) -> None:
        entry = self.challenges.get(challenge_name)
        if not entry:
            return
        entry.attempts += 1
        if entry.attempts >= entry.max_attempts:
            entry.transition_to(ChallengeStatus.FAILED, f"Max attempts reached: {reason}")
        else:
            # Upgrade tier on failure: fast -> expert -> racing
            if entry.tier == "fast":
                entry.tier = "expert"
            elif entry.tier == "expert":
                entry.tier = "racing"
            entry.transition_to(ChallengeStatus.TRIAGED, f"Upgraded to tier={entry.tier} after attempt {entry.attempts}")
        self.save_state()

    def next_ready_challenges(self) -> list[ChallengeEntry]:
        """Return triaged challenges sorted by priority, up to available capacity."""
        currently_solving = sum(1 for c in self.challenges.values() if c.status is ChallengeStatus.SOLVING)
        available_slots = max(0, self.max_concurrent_challenges - currently_solving)
        if available_slots <= 0:
            return []

        candidates = [c for c in self.challenges.values() if c.status is ChallengeStatus.TRIAGED]
        candidates.sort(key=lambda c: c.priority, reverse=True)
        return candidates[:available_slots]
