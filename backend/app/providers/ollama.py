from __future__ import annotations
import json
import os
import uuid
from typing import Callable
import httpx
from app.core.types import ProviderResult, Usage
from app.providers.base import Provider

class OllamaProvider(Provider):
    name = "ollama"
    supports_per_call_output_tokens = True
    supports_streaming = True  # on_text: hiện chữ dần ở ô chat sản phẩm

    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: float | None = None):
        self.model = model or os.getenv("LOCAL_LLM_MODEL", "qwen3:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout or float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS", "180"))
        self.temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.1"))
        self.max_output_tokens = max(64, int(os.getenv("MAX_OUTPUT_TOKENS", "700")))

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        return await self._generate(system=system, user=user)

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict,
        max_output_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ProviderResult:
        return await self._generate(
            system=system,
            user=user,
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
            on_text=on_text,
        )

    async def generate_grounded(
        self, *, system: str, user: str, evidence_ids: list[str], on_text: Callable[[str], None] | None = None,
        max_output_tokens: int | None = None,
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
        return await self._generate(system=system, user=user, response_schema=schema, max_output_tokens=max_output_tokens, on_text=on_text)

    async def _generate(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict | None = None,
        max_output_tokens: int | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ProviderResult:
        output_limit = (
            self.max_output_tokens
            if max_output_tokens is None
            else max(64, int(max_output_tokens))
        )
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
            "options": {
                "temperature": self.temperature,
                "num_predict": output_limit,
            },
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
            text, data = await self._stream(payload, on_text)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            text = (data.get("message") or {}).get("content", "")
        inp = int(data.get("prompt_eval_count") or 0)
        out = int(data.get("eval_count") or 0)
        return ProviderResult(text=text, usage=Usage(inp, out), request_id="ollama_"+uuid.uuid4().hex[:10], model=self.model)

    async def _stream(self, payload: dict, on_text: Callable[[str], None]) -> tuple[str, dict]:
        """Cùng yêu cầu nhưng stream=True: gọi on_text với toàn bộ chữ đã nhận; trả chữ đủ và dòng cuối (có token)."""
        parts: list[str] = []
        last: dict = {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json={**payload, "stream": True}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    last = json.loads(line)
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
