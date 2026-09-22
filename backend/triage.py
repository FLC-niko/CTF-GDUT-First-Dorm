"""Challenge triage and technical route assessment.

LLM performs fast initial classification, hypothesizing technical routes,
identifying required toolchains, and suggesting solver tier (Fast/Expert/Racing).
Deterministic heuristics act as a robust fallback.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

from backend.prompts import ChallengeMeta

logger = logging.getLogger(__name__)

SolverTier = Literal["fast", "expert", "racing"]


@dataclass(frozen=True, slots=True)
class TriageReport:
    challenge_name: str
    category: str
    complexity_score: int  # 1 (trivial/warmup) to 5 (extremely difficult)
    suggested_tier: SolverTier
    technical_routes: tuple[str, ...] = ()
    initial_hypotheses: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriageReport:
        return cls(
            challenge_name=str(data.get("challenge_name", "")),
            category=str(data.get("category", "unknown")),
            complexity_score=int(data.get("complexity_score", 3)),
            suggested_tier=data.get("suggested_tier", "fast"),
            technical_routes=tuple(data.get("technical_routes", ())),
            initial_hypotheses=tuple(data.get("initial_hypotheses", ())),
            required_tools=tuple(data.get("required_tools", ())),
            summary=str(data.get("summary", "")),
        )


class ChallengeTriager:
    """Performs triage on incoming challenges using heuristics or lightweight LLM."""

    def __init__(self, triage_model: str | None = None) -> None:
        self.triage_model = triage_model

    def heuristic_triage(
        self,
        meta: ChallengeMeta,
        distfile_names: list[str] | tuple[str, ...] = (),
    ) -> TriageReport:
        """Deterministic heuristic triage when no model is available or for offline testing."""
        category = (meta.category or "misc").lower().strip()
        tags = [t.lower() for t in (meta.tags or ())]
        names = [n.lower() for n in distfile_names]

        routes: list[str] = []
        hypotheses: list[str] = []
        tools: list[str] = []
        tier: SolverTier = "fast"
        complexity = 2

        if category in {"pwn", "binary"}:
            tools.extend(["pwntools", "gdb", "checksec", "ropgadget"])
            routes.append("Binary exploitation (stack/heap buffer overflow, ROP, format string)")
            hypotheses.append(
                "Inspect binary protections via checksec; check for dangerous functions"
            )
            if any("heap" in t for t in tags) or any("kernel" in t for t in tags):
                complexity = 4
                tier = "expert"
            else:
                complexity = 3
                tier = "fast"

        elif category in {"reverse", "reversing", "re"}:
            tools.extend(["radare2", "ghidra", "angr", "strings"])
            routes.append("Static/dynamic reverse engineering (control flow analysis, keygen, vm)")
            hypotheses.append("Decompile and identify string comparisons or encryption routines")
            if any("vm" in t for t in tags) or any("obfuscat" in t for t in tags):
                complexity = 4
                tier = "expert"
            else:
                complexity = 3
                tier = "fast"

        elif category in {"crypto", "cryptography"}:
            tools.extend(["sage", "python3-pycryptodome", "z3", "cado-nfs"])
            routes.append(
                "Cryptographic analysis (weak keys, PRNG predictability, algebraic attack)"
            )
            hypotheses.append(
                "Analyze key generation and mathematical structure; search for known attack patterns"
            )
            if any(n.endswith(".sage") for n in names) or any("lattice" in t for t in tags):
                complexity = 4
                tier = "expert"
            else:
                complexity = 2
                tier = "fast"

        elif category in {"web"}:
            tools.extend(["curl", "requests", "sqlmap", "jwt-tool"])
            routes.append(
                "Web vulnerability assessment (SQLi, SSRF, XSS, deserialization, auth bypass)"
            )
            hypotheses.append("Probe input parameters and review client/server source scripts")
            complexity = 2
            tier = "fast"

        else:
            tools.extend(["file", "binwalk", "strings", "exiftool", "stegseek", "zsteg"])
            routes.append(
                "Forensics/Misc artifact analysis (steganography, network pcap, memory dump)"
            )
            hypotheses.append("Inspect metadata and carving embedded archives")
            complexity = 1
            tier = "fast"

        # High point value challenges naturally escalate complexity
        if meta.value and meta.value >= 500:
            complexity = max(complexity, 4)
            tier = "expert"

        return TriageReport(
            challenge_name=meta.name,
            category=category,
            complexity_score=complexity,
            suggested_tier=tier,
            technical_routes=tuple(routes),
            initial_hypotheses=tuple(hypotheses),
            required_tools=tuple(tools),
            summary=f"Automated heuristic triage for {meta.name} ({category}): tier={tier}, score={complexity}/5",
        )

    async def triage(
        self,
        meta: ChallengeMeta,
        distfile_names: list[str] | tuple[str, ...] = (),
        challenge_desc: str = "",
    ) -> TriageReport:
        """Run triage analysis on a challenge."""
        # When a triage model is configured, an LLM call could be performed;
        # otherwise (and for determinism), heuristic triage provides reliable baseline.
        return self.heuristic_triage(meta, distfile_names)
