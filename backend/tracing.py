"""Per-tool-call JSONL event tracing — one file per solver, streamable via tail -f."""

from __future__ import annotations

import atexit
import json
import re
import time
from pathlib import Path


def _sanitize(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "flag",
    "password",
    "secret",
    "token",
}
_FLAG_PATTERN = re.compile(r"(?i)\b(?:flag|ctf|key|gdut|d0g3)[-_a-z0-9]*\{[^{}\r\n]{1,512}\}")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
)


def _redact_text(value: str) -> str:
    redacted = _FLAG_PATTERN.sub("<redacted-flag>", value)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("<redacted-secret>", redacted)
    return redacted


def _redact_value(value, key: str | None = None):
    if key and key.lower() in _SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {str(k): _redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


class SolverTracer:
    """Append-only JSONL event tracer. Flushes every write for tail -f streaming."""

    def __init__(self, challenge_name: str, model_id: str, log_dir: str = "logs") -> None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.path = str(
            Path(log_dir) / f"trace-{_sanitize(challenge_name)}-{_sanitize(model_id)}-{ts}.jsonl"
        )
        self._fh = open(self.path, "a")
        atexit.register(self._close)

    def close(self) -> None:
        """Explicitly close the trace file. Safe to call multiple times."""
        if not self._fh.closed:
            try:
                self._fh.close()
            except Exception:
                pass

    _close = close  # atexit compat

    def _write(self, event: dict) -> None:
        try:
            safe_event = _redact_value(event)
            self._fh.write(json.dumps({"ts": time.time(), **safe_event}) + "\n")
            self._fh.flush()
        except Exception:
            pass

    def tool_call(self, tool_name: str, args: dict | str, step: int) -> None:
        if tool_name == "submit_flag":
            args_str = "<redacted>"
        else:
            args_str = args if isinstance(args, str) else json.dumps(args)
        self._write({"type": "tool_call", "tool": tool_name, "args": args_str[:2000], "step": step})

    def tool_result(self, tool_name: str, result: str, step: int) -> None:
        self._write(
            {"type": "tool_result", "tool": tool_name, "result": result[:2000], "step": step}
        )

    def model_response(
        self, text: str, step: int, input_tokens: int = 0, output_tokens: int = 0
    ) -> None:
        self._write(
            {
                "type": "model_response",
                "text": text[:1000],
                "step": step,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )

    def usage(
        self, input_tokens: int, output_tokens: int, cache_read: int, cost_usd: float
    ) -> None:
        self._write(
            {
                "type": "usage",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read,
                "cost_usd": round(cost_usd, 6),
            }
        )

    def event(self, kind: str, **kwargs) -> None:
        self._write({"type": kind, **kwargs})
