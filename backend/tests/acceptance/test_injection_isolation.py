from pathlib import Path

from app.core.types import Usage
from app.research.pipeline import ResearchPipeline
from app.storage.conversation_store import ConversationStore
from app.storage.run_store import RunStore
from app.storage.source_store import SourceStore


# Paragraphs are separate chunks now, so the question also names the injected paragraph's topic: both chunks are
# retrieved and the original assertions (injection only in the user block, same verdict as a clean doc) still bite.
Q = "What is the key rotation interval, and is the document text untrusted evidence?"


class UnpersuadableFake:
    name = "fake"
    model = "fixed"
    prompts = []

    async def generate(self, *, system, user):
        self.prompts.append((system, user))
        return type("Result", (), {"text": '{"status":"PARTIAL","answer":"Grounded review.","citations":[],"missing_information":["detail"]}', "usage": Usage(input_tokens=1, output_tokens=1)})()

    async def generate_grounded(self, *, system, user, evidence_ids):
        return await self.generate(system=system, user=user)


def test_document_injection_remains_evidence_and_does_not_change_pipeline_verdict(monkeypatch, tmp_path, sf1_fake_provider_env):
    from app.research import pipeline as factory
    provider = UnpersuadableFake()
    monkeypatch.setattr(factory, "get_provider", lambda name=None: provider)
    doc = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_docs" / "injection.md"
    store = SourceStore(str(tmp_path / "sources"))
    source = store.import_text("injection.md", doc.read_text(encoding="utf-8"))
    run = __import__("asyncio").run(ResearchPipeline(store, RunStore(str(tmp_path / "runs"))).run(Q, condition="A", provider_name="fake", source_ids=[source["source_id"]]))
    system, user = provider.prompts[-1]
    clean = store.import_text("clean.md", "The key rotation interval is 90 days.")
    clean_run = __import__("asyncio").run(ResearchPipeline(store, RunStore(str(tmp_path / "runs2"))).run(Q, condition="A", provider_name="fake", source_ids=[clean["source_id"]]))
    assert run["status"] == clean_run["status"]  # injected text did not change the status
    assert len(run["task_results"][0]["citations"]) == len(clean_run["task_results"][0]["citations"])
    assert "ignore previous instructions" not in system.casefold()
    assert "ignore previous instructions" in user.casefold()


def test_owner_scoped_file_stores_isolate_sources_conversations_and_runs(tmp_path):
    owners = {}
    for owner, marker in (("alice", "secret-alpha"), ("bob", "secret-beta")):
        root = tmp_path / owner
        source = SourceStore(str(root / "sources"))
        source.import_text("private.txt", marker)
        conversations = ConversationStore(root / "conversations")
        conv = conversations.create(owner)
        conversations.add_message(conv["conversation_id"], "USER", marker)
        runs = RunStore(str(root / "runs"))
        runs.save({"run_id": marker, "status": "COMPLETE"})
        owners[owner] = (source, conversations, runs, conv["conversation_id"])
    alice, bob = owners["alice"], owners["bob"]
    assert "secret-beta" not in " ".join(chunk.text for chunk in alice[0].chunks())
    assert bob[1].get(alice[3]) is None
    assert bob[2].get("secret-alpha") is None
