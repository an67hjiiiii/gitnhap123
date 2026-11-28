from __future__ import annotations
import hashlib
import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass, asdict
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)

PROFILE_CONDITIONS = {
    "m0": {"A"},
    "m1": {"A", "B", "C"},
    "m2": {"A", "B", "C", "C-P", "C-N", "C-O"},
    # Engineering-only profile used to test future wiring before a milestone is claimed.
    "dev": {"A", "B", "C", "C-P", "C-N", "C-O"},
}

@dataclass(frozen=True)
class RuntimeConfig:
    implementation_profile: str
    provider: str
    local_model: str
    task_top_k: int
    planning_top_k: int
    max_context_tokens: int
    max_output_tokens: int
    max_run_tokens: int
    retry_limit: int
    retrieval_min_score: float
    task_plan_max_output_tokens: int = 700
    # Chỉ dùng cho ô chat sản phẩm; thực nghiệm A/B/C giữ max_output_tokens như cũ.
    synthesis_max_output_tokens: int = 1800

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        profile = os.getenv("IMPLEMENTATION_PROFILE", "m0").strip().lower()
        if profile not in PROFILE_CONDITIONS:
            raise ValueError(f"Unsupported IMPLEMENTATION_PROFILE={profile}")
        return cls(
            implementation_profile=profile,
            provider=os.getenv("PROVIDER", "fake").strip().lower(),
            local_model=os.getenv("LOCAL_LLM_MODEL", "qwen3:4b").strip(),
            task_top_k=max(1, int(os.getenv("TASK_TOP_K", "6"))),
            planning_top_k=max(1, int(os.getenv("PLANNING_TOP_K", "3"))),
            max_context_tokens=max(256, int(os.getenv("MAX_CONTEXT_TOKENS", "3000"))),
            max_output_tokens=max(64, int(os.getenv("MAX_OUTPUT_TOKENS", "700"))),
            max_run_tokens=max(512, int(os.getenv("MAX_RUN_TOKENS", "12000"))),
            retry_limit=max(0, int(os.getenv("RETRY_LIMIT", "1"))),
            retrieval_min_score=max(0.0, float(os.getenv("MIN_RETRIEVAL_SCORE", "0.18"))),
            task_plan_max_output_tokens=max(
                64,
                int(os.getenv("TASK_PLAN_MAX_OUTPUT_TOKENS", "700")),
            ),
            synthesis_max_output_tokens=max(
                64,
                int(os.getenv("SYNTHESIS_MAX_OUTPUT_TOKENS", "1800")),
            ),
        )

    def allowed_conditions(self) -> list[str]:
        return sorted(PROFILE_CONDITIONS[self.implementation_profile])

    def assert_condition(self, condition: str) -> None:
        if condition not in PROFILE_CONDITIONS[self.implementation_profile]:
            allowed = ", ".join(self.allowed_conditions())
            raise ValueError(
                f"Condition {condition} is not available in profile {self.implementation_profile}. "
                f"Allowed: {allowed}"
            )

    def public_dict(self) -> dict:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(self.public_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_KEEP_ALIVE_RE = re.compile(r"^\d+(?:\.\d+)?(?:ns|us|µs|ms|s|m|h)?$", re.IGNORECASE)
_UNSET_VALUES = frozenset({"default", "off", "none", "unset"})


def _normalize_keep_alive(raw: Any, *, strict: bool) -> str | int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        if strict:
            raise ValueError("keep_alive cannot be a boolean")
        return None
    if isinstance(raw, (int, float)):
        if raw < 0 or not (raw == raw):
            if strict:
                raise ValueError("Permanent or negative keep_alive (-1) is disallowed")
            return None
        return int(raw) if isinstance(raw, int) or raw.is_integer() else f"{raw}s"
    text = str(raw).strip()
    if not text or text.lower() in _UNSET_VALUES:
        return None
    if text.startswith("-") or not _KEEP_ALIVE_RE.fullmatch(text):
        if strict:
            raise ValueError(f"Invalid or permanent keep_alive value: {text!r}")
        return None
    if text.isdigit():
        return int(text)
    return text.lower()


def resolve_ollama_keep_alive(
    explicit: str | int | float | None = None,
    *,
    product: bool = False,
    embed: bool = False,
) -> str | int | None:
    """Resolve safe, finite Ollama keep_alive duration without forcing permanent residency (-1)."""
    if explicit is not None:
        return _normalize_keep_alive(explicit, strict=True)
    if embed:
        raw_embed = os.getenv("OLLAMA_EMBED_KEEP_ALIVE")
        if raw_embed is not None and raw_embed.strip():
            return _normalize_keep_alive(raw_embed, strict=False)
        raw_global = os.getenv("OLLAMA_KEEP_ALIVE")
        if raw_global is not None and raw_global.strip():
            return _normalize_keep_alive(raw_global, strict=False)
        return None
    if product:
        raw_prod = os.getenv("PRODUCT_OLLAMA_KEEP_ALIVE")
        if raw_prod is not None and raw_prod.strip():
            return _normalize_keep_alive(raw_prod, strict=False)
        raw_global = os.getenv("OLLAMA_KEEP_ALIVE")
        if raw_global is not None and raw_global.strip():
            return _normalize_keep_alive(raw_global, strict=False)
        return "10m"
    raw_global = os.getenv("OLLAMA_KEEP_ALIVE")
    if raw_global is not None and raw_global.strip():
        return _normalize_keep_alive(raw_global, strict=False)
    return None


def resolve_ollama_generation_config(
    *,
    product: bool = False,
    num_ctx: int | None = None,
    max_output_tokens: int | None = None,
    timeout: float | None = None,
    keep_alive: str | int | float | None = None,
) -> dict[str, Any]:
    """Centralized generation parameter resolution preserving Research A/B/C defaults and caller overrides."""
    from app.research.token_budget import resolve_max_safe_num_ctx, resolve_product_num_ctx

    effective_num_ctx: int | None = None
    if num_ctx is not None:
        effective_num_ctx = max(512, min(int(num_ctx), resolve_max_safe_num_ctx()))
    elif product:
        effective_num_ctx = resolve_product_num_ctx()
    return {
        "num_ctx": effective_num_ctx,
        "keep_alive": resolve_ollama_keep_alive(keep_alive, product=product, embed=False),
        "max_output_tokens": max_output_tokens,
        "timeout": timeout,
    }


def ollama_call_options(
    provider: Any,
    *,
    product: bool = True,
    num_ctx: int | None = None,
    max_output_tokens: int | None = None,
    timeout: float | None = None,
    keep_alive: str | int | float | None = None,
) -> dict[str, Any]:
    """Filter centralized generation options to capabilities explicitly supported by `provider`."""
    cfg = resolve_ollama_generation_config(
        product=product,
        num_ctx=num_ctx,
        max_output_tokens=max_output_tokens,
        timeout=timeout,
        keep_alive=keep_alive,
    )
    opts: dict[str, Any] = {}
    if cfg["num_ctx"] is not None and getattr(provider, "supports_num_ctx", False):
        opts["num_ctx"] = cfg["num_ctx"]
    if cfg["keep_alive"] is not None and getattr(provider, "supports_keep_alive", False):
        opts["keep_alive"] = cfg["keep_alive"]
    if cfg["max_output_tokens"] is not None and getattr(provider, "supports_per_call_output_tokens", False):
        opts["max_output_tokens"] = cfg["max_output_tokens"]
    if cfg["timeout"] is not None and getattr(provider, "supports_per_call_timeout", False):
        opts["timeout"] = cfg["timeout"]
    return opts
