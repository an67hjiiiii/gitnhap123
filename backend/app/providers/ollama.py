from __future__ import annotations
import asyncio
import json
import os
import threading
import uuid
from typing import Callable
import httpx
from app.core.types import ProviderResult, Usage
from app.providers.base import Provider
from app.research.token_budget import count_prompt_tokens, resolve_max_safe_num_ctx

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

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: float | None = None):
        self.model = model or os.getenv("LOCAL_LLM_MODEL", "qwen3:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self._explicit_timeout = timeout is not None
        self.timeout = float(timeout) if timeout is not None else float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180"))
        self.temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.1"))
        self.max_output_tokens = max(64, int(os.getenv("MAX_OUTPUT_TOKENS", "700")))

    async def generate(
        self,
        *,
        system: str,
        user: str,
        num_ctx: int | None = None,
        timeout: float | None = None,
    ) -> ProviderResult:
        return await self._generate(system=system, user=user, num_ctx=num_ctx, timeout=timeout)

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
    ) -> ProviderResult:
        return await self._generate(
            system=system,
            user=user,
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
            on_text=on_text,
            num_ctx=num_ctx,
            timeout=timeout,
        )

    async def generate_grounded(
        self, *, system: str, user: str, evidence_ids: list[str], on_text: Callable[[str], None] | None = None,
        max_output_tokens: int | None = None, num_ctx: int | None = None, timeout: float | None = None,
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
        return await self._generate(
            system=system,
            user=user,
            response_schema=schema,
            max_output_tokens=max_output_tokens,
            on_text=on_text,
            num_ctx=num_ctx,
            timeout=timeout,
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
        effective_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        payload = {
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
        if on_text is not None:
            text, data = await self._stream(payload, on_text, timeout=effective_timeout)
        else:
            connect_retries = max(0, min(2, int(os.getenv("OLLAMA_CONNECT_RETRIES", "1") or 0)))
            last_exc: Exception | None = None
            response = None
            for attempt in range(connect_retries + 1):
                try:
                    response = await _async_client(effective_timeout).post(f"{self.base_url}/api/chat", json=payload)
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
        inp = int(data.get("prompt_eval_count") or 0)
        out = int(data.get("eval_count") or 0)
        return ProviderResult(text=text, usage=Usage(inp, out), request_id="ollama_"+uuid.uuid4().hex[:10], model=self.model)

    async def _stream(self, payload: dict, on_text: Callable[[str], None], *, timeout: float | None = None) -> tuple[str, dict]:
        """Cùng yêu cầu nhưng stream=True: gọi on_text với toàn bộ chữ đã nhận; trả chữ đủ và dòng cuối (có token)."""
        parts: list[str] = []
        last: dict = {}
        effective_timeout = self.timeout if timeout is None else max(1.0, float(timeout))
        async with _async_client(effective_timeout).stream("POST", f"{self.base_url}/api/chat", json={**payload, "stream": True}) as response:
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
                    parts.append(piece)
                    on_text("".join(parts))
        return "".join(parts), last

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
