from __future__ import annotations
import asyncio
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable
import httpx
from app.core.config import resolve_ollama_keep_alive
from app.core.types import ProviderResult, Usage
from app.providers.base import Provider
from app.research.token_budget import count_prompt_tokens, resolve_max_safe_num_ctx

_UNSET = object()
_GENERATION_STAGE: ContextVar[str | None] = ContextVar("ollama_generation_stage", default=None)
_KEEP_ALIVE_OVERRIDE: ContextVar[Any] = ContextVar("ollama_keep_alive_override", default=_UNSET)


@contextmanager
def generation_stage(stage: str | None):
    """Attach the active pipeline/analysis stage cleanly without altering provider method signatures."""
    tok = _GENERATION_STAGE.set(stage)
    try:
        yield
    finally:
        _GENERATION_STAGE.reset(tok)


def _ns_to_ms(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value) / 1_000_000.0, 2)
    return None

# Một AsyncClient cho mỗi (vòng lặp sự kiện, timeout), dùng lại giữa các lần gọi. Đo 23/11: tạo client mới mỗi lần
# gọi mô hình tốn 0,4–1,5 s nạp chứng chỉ SSL ngay trong vòng lặp sự kiện, làm luồng sự kiện ô chat tới trình duyệt muộn.
_CLIENTS_LOCK = threading.Lock()
_CLIENTS: dict[tuple[int, float], tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}


def _async_client(timeout: float) -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    t = round(max(1.0, float(timeout)), 3)
    key = (id(loop), t)
    with _CLIENTS_LOCK:
        hit = _CLIENTS.get(key)
        if hit and hit[0] is loop and not getattr(hit[1], "is_closed", False):
            return hit[1]
        for k, (lp, _client) in list(_CLIENTS.items()):  # bỏ client của vòng lặp đã đóng
            if lp.is_closed():
                _CLIENTS.pop(k, None)
        if len(_CLIENTS) >= 32:
            _CLIENTS.clear()
        client = httpx.AsyncClient(timeout=httpx.Timeout(t, connect=min(15.0, t)))
        _CLIENTS[key] = (loop, client)
        return client

class OllamaProvider(Provider):
    name = "ollama"
    supports_per_call_output_tokens = True
    supports_num_ctx = True
    supports_per_call_timeout = True
    supports_streaming = True  # on_text: hiện chữ dần ở ô chat sản phẩm
    supports_keep_alive = True

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: float | None = None):
        self.model = model or os.getenv("LOCAL_LLM_MODEL", "qwen3:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self._explicit_timeout = timeout is not None
        self.timeout = float(timeout) if timeout is not None else float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180"))
        self.temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.1"))
        self.max_output_tokens = max(64, int(os.getenv("MAX_OUTPUT_TOKENS", "700")))

    def _extra_headers(self) -> dict[str, str]:
        sess = os.getenv("QA_RUN_SESSION", "").strip()
        return {"X-QA-Run-Session": sess} if sess else {}

    async def _call_generate(self, *, keep_alive: str | int | float | None = None, **kwargs) -> ProviderResult:
        if keep_alive is None:
            return await self._generate(**kwargs)
        tok = _KEEP_ALIVE_OVERRIDE.set(keep_alive)
        try:
            return await self._generate(**kwargs)
        finally:
            _KEEP_ALIVE_OVERRIDE.reset(tok)

    async def generate(
        self,
        *,
        system: str,
        user: str,
        num_ctx: int | None = None,
        timeout: float | None = None,
        keep_alive: str | int | float | None = None,
    ) -> ProviderResult:
        return await self._call_generate(
            system=system, user=user, num_ctx=num_ctx, timeout=timeout, keep_alive=keep_alive
        )

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict,
        max_output_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        num_ctx: int | None = None,
        timeout: float | None = None,
        keep_alive: str | int | float | None = None,
    ) -> ProviderResult:
        return await self._call_generate(
            system=system,
            user=user,
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
            on_text=on_text,
            num_ctx=num_ctx,
            timeout=timeout,
            keep_alive=keep_alive,
        )

    async def generate_grounded(
        self, *, system: str, user: str, evidence_ids: list[str], on_text: Callable[[str], None] | None = None,
        max_output_tokens: int | None = None, num_ctx: int | None = None, timeout: float | None = None,
        keep_alive: str | int | float | None = None,
    ) -> ProviderResult:
        # grounded-output-v1: IDs come from selected canonical chunks, not model text.
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["COMPLETE", "PARTIAL", "NO_EVIDENCE"]},
                "answer": {"type": "string"},
                "citations": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(dict.fromkeys(evidence_ids))},
                },
                "missing_information": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "answer", "citations", "missing_information"],
            "additionalProperties": False,
        }
        return await self._call_generate(
            system=system,
            user=user,
            response_schema=schema,
            max_output_tokens=max_output_tokens,
            on_text=on_text,
            num_ctx=num_ctx,
            timeout=timeout,
            keep_alive=keep_alive,
        )

    async def _generate(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict | None = None,
        max_output_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
        num_ctx: int | None = None,
        timeout: float | None = None,
    ) -> ProviderResult:
        output_limit = (
            self.max_output_tokens
            if max_output_tokens is None
            else max(64, int(max_output_tokens))
        )
        effective_num_ctx: int | None = None
        if num_ctx is not None:
            effective_num_ctx = max(512, min(int(num_ctx), resolve_max_safe_num_ctx()))
        elif os.getenv("OLLAMA_NUM_CTX", "").strip():
            try:
                effective_num_ctx = max(512, min(int(os.getenv("OLLAMA_NUM_CTX", "0")), resolve_max_safe_num_ctx()))
            except ValueError:
                effective_num_ctx = None
        options: dict[str, float | int] = {
            "temperature": self.temperature,
            "num_predict": output_limit,
        }
        if effective_num_ctx is not None:
            prompt_tokens = count_prompt_tokens(system) + count_prompt_tokens(user)
            if prompt_tokens + 64 >= effective_num_ctx:
                raise ValueError(
                    f"Prompt tokens ({prompt_tokens}) exceed safe num_ctx budget ({effective_num_ctx})"
                )
            options["num_ctx"] = effective_num_ctx
        ka_override = _KEEP_ALIVE_OVERRIDE.get()
        effective_keep_alive = (
            resolve_ollama_keep_alive(ka_override)
            if ka_override is not _UNSET
            else resolve_ollama_keep_alive()
        )
        effective_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            # Qwen3 and other reasoning-capable Ollama models may emit a thinking
            # channel unless this is disabled explicitly. Research pipelines
            # need clean machine-readable outputs and comparable token/latency.
            "think": False,
            "messages": [
                {"role":"system","content":system},
                {"role":"user","content":user},
            ],
            "options": options,
        }
        if effective_keep_alive is not None:
            payload["keep_alive"] = effective_keep_alive
        marker = system.upper()
        if any(
            x in marker
            for x in (
                "VANILLA_RAG_ANSWERER",
                "TASK_DECOMPOSER",
                "TASK_PLAN_BUILDER",
                "OBLIGATION_CONCERN_EXTRACTOR",
                "WORKER",
            )
        ):
            payload["format"] = "json"
        if response_schema is not None:
            payload["format"] = response_schema
        t0 = time.perf_counter()
        ttft_ms: float | None = None
        if on_text is not None:
            text, data, ttft_ms = await self._stream(payload, on_text, timeout=effective_timeout, start_ts=t0)
        else:
            connect_retries = max(0, min(2, int(os.getenv("OLLAMA_CONNECT_RETRIES", "1") or 0)))
            last_exc: Exception | None = None
            response = None
            post_kwargs: dict[str, Any] = {"json": payload}
            extra_hdrs = self._extra_headers()
            if extra_hdrs:
                post_kwargs["headers"] = extra_hdrs
            for attempt in range(connect_retries + 1):
                try:
                    response = await _async_client(effective_timeout).post(
                        f"{self.base_url}/api/chat", **post_kwargs
                    )
                    break
                except httpx.ConnectError as exc:
                    last_exc = exc
                    if attempt >= connect_retries:
                        raise
                    await asyncio.sleep(0.05 * (attempt + 1))
            if response is None and last_exc is not None:
                raise last_exc
            response.raise_for_status()
            data = response.json()
            text = (data.get("message") or {}).get("content", "")
        wall_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        inp = int(data.get("prompt_eval_count") or 0)
        out = int(data.get("eval_count") or 0)
        provider_metrics = {
            "stage": _GENERATION_STAGE.get(),
            "wall_ms": wall_ms,
            "ttft_ms": ttft_ms,
            "total_duration_ms": _ns_to_ms(data.get("total_duration")),
            "load_duration_ms": _ns_to_ms(data.get("load_duration")),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "prompt_eval_duration_ms": _ns_to_ms(data.get("prompt_eval_duration")),
            "eval_count": data.get("eval_count"),
            "eval_duration_ms": _ns_to_ms(data.get("eval_duration")),
            "effective_num_ctx": effective_num_ctx,
            "effective_keep_alive": effective_keep_alive,
        }
        return ProviderResult(
            text=text,
            usage=Usage(inp, out),
            request_id="ollama_"+uuid.uuid4().hex[:10],
            model=self.model,
            metrics=provider_metrics,
        )

    async def _stream(
        self,
        payload: dict,
        on_text: Callable[[str], None],
        *,
        timeout: float | None = None,
        start_ts: float | None = None,
    ) -> tuple[str, dict, float | None]:
        """Cùng yêu cầu nhưng stream=True: gọi on_text với toàn bộ chữ đã nhận; trả chữ đủ, dòng cuối và TTFT (ms)."""
        parts: list[str] = []
        last: dict = {}
        t0 = start_ts if start_ts is not None else time.perf_counter()
        ttft_ms: float | None = None
        effective_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        stream_kwargs: dict[str, Any] = {"json": {**payload, "stream": True}}
        extra_hdrs = self._extra_headers()
        if extra_hdrs:
            stream_kwargs["headers"] = extra_hdrs
        async with _async_client(effective_timeout).stream(
            "POST", f"{self.base_url}/api/chat", **stream_kwargs
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    last = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("ollama stream error: malformed NDJSON chunk") from exc
                if last.get("error"):
                    raise RuntimeError(f"ollama stream error: {last['error']}")
                piece = (last.get("message") or {}).get("content", "")
                if piece:
                    if ttft_ms is None:
                        ttft_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                    parts.append(piece)
                    on_text("".join(parts))
        return "".join(parts), last, ttft_ms

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
        models = []
        for m in data.get("models", []):
            models.append({
                "name": m.get("name"),
                "model": m.get("model"),
                "digest": m.get("digest"),
                "size": m.get("size"),
                "modified_at": m.get("modified_at"),
            })
        configured = next((m for m in models if m.get("name") == self.model or m.get("model") == self.model), None)
        return {"ok": True, "models": models, "configured_model": self.model, "configured_model_info": configured}
