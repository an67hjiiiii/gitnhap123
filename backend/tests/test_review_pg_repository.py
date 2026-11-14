"""Review repository parity and durable queue contracts without external services."""

import hashlib
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from threading import Barrier

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, event, func, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.review.engine import FakeReviewEngine
from app.review.repository import InMemoryCaseRepository
from app.review.schemas import (
    CaseStatus, Decision, Evidence, Finding, JobState, Requirement,
    RequirementOrigin, ReviewCase, RunJob, Verdict,
)
from app.review.service import ReviewCaseService
from app.review_adapters.pg_repository import PostgresCaseRepository
from app.storage.postgres.base import Base
from app.storage.postgres.review_models import (
    ReviewCaseRecord, ReviewFindingRecord, ReviewRequirementRecord,
    ReviewRunEventRecord, ReviewRunJobRecord,
)


NOW = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
TABLES = [model.__table__ for model in (
    ReviewCaseRecord, ReviewRequirementRecord, ReviewFindingRecord,
    ReviewRunJobRecord, ReviewRunEventRecord,
)]
BACKEND = Path(__file__).resolve().parents[1]


def make_case(id="case-1", owner="alice"):
    return ReviewCase(
        id=id, owner_user_id=owner, title="Audit", request_text="Check policy.",
        source_ids=["source-1"], created_at=NOW, updated_at=NOW,
    )


def requirement(id="requirement-1", order=0, case_id="case-1"):
    return Requirement(
        id=id, case_id=case_id, text="Check policy", origin=RequirementOrigin.USER,
        confirmed=True, order=order,
    )


def finding(id="finding-1"):
    return Finding(
        id=id, case_id="case-1", requirement_id="requirement-1", verdict=Verdict.SATISFIED,
        evidence=[Evidence(evidence_id="e1", source_id="source-1", locator="p1", excerpt="Policy")],
        review=Decision.EDIT, edited_text="Reviewed policy", confidence="L2",
    )


def job(id="job-1", seq=1, case_id="case-1"):
    return RunJob(id=id, case_id=case_id, state=JobState.QUEUED, seq=seq, budget={"tasks": 2})


def sqlite_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture(autouse=True)
def fake_environment(monkeypatch, sf1_vector_store):
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")


@pytest.fixture
def storage(request):
    backend = request.cls.backend
    if backend == "memory":
        yield InMemoryCaseRepository(), None
        return
    if backend == "postgresql":
        # Stable names per test/process avoid collisions without random identifiers.
        tmp_path = request.getfixturevalue("tmp_path")
        digest = hashlib.sha256(f"{tmp_path}:{os.getpid()}".encode()).hexdigest()[:24]
        schema = f"review_test_{digest}"
        engine = create_engine(os.environ["TEST_DATABASE_URL"])
        assert engine.dialect.name == "postgresql"
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        bound = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = bound = sqlite_engine()
        schema = None
    try:
        Base.metadata.create_all(bound, tables=TABLES)
        factory = sessionmaker(bind=bound, expire_on_commit=False, autoflush=False)
        yield PostgresCaseRepository(factory), factory
    finally:
        # Never include the product tables; DROP SCHEMA has no CASCADE fallback.
        Base.metadata.drop_all(bound, tables=TABLES)
        if schema:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema))
        engine.dispose()


class RepositoryBehavior:
    def test_case_round_trip_upsert_and_detachment(self, storage):
        repo, _ = storage
        case = make_case()
        repo.save_case("alice", case)
        assert repo.get_case("alice", case.id) == case
        case.title, case.status = "Updated", CaseStatus.READY
        case.updated_at += timedelta(seconds=1)
        repo.save_case("alice", case)
        assert repo.list_cases("alice") == [case]
        detached = repo.get_case("alice", case.id)
        detached.source_ids.append("foreign")
        assert repo.get_case("alice", case.id) == case
        assert repo.get_case("alice", "missing") is None

    def test_owner_isolation_for_reads_and_writes(self, storage):
        repo, _ = storage
        repo.save_case("alice", make_case())
        repo.save_case("bob", make_case("case-2", "bob"))
        repo.save_requirements("alice", "case-1", [requirement()])
        repo.save_findings("alice", "case-1", [finding()])
        repo.save_job("alice", job())
        assert repo.get_case("bob", "case-1") is None
        assert [case.id for case in repo.list_cases("bob")] == ["case-2"]
        for getter in (repo.get_requirements, repo.get_findings, repo.get_jobs):
            assert getter("bob", "case-1") == []
            assert getter("alice", "missing") == []
        for save, value in ((repo.save_requirements, [requirement()]), (repo.save_findings, [finding()])):
            with pytest.raises(KeyError):
                save("bob", "case-1", value)
            with pytest.raises(KeyError):
                save("alice", "missing", [])
        with pytest.raises(KeyError):
            repo.save_job("bob", job())
        with pytest.raises(ValueError, match="owner mismatch"):
            repo.save_case("bob", make_case())

    def test_requirements_replace_reorder_clear_and_detach(self, storage):
        repo, _ = storage
        repo.save_case("alice", make_case())
        first, second = requirement(), requirement("requirement-2", 1)
        repo.save_requirements("alice", "case-1", [first, second])
        assert repo.get_requirements("alice", "case-1") == [first, second]
        first.order, second.order = 1, 0
        repo.save_requirements("alice", "case-1", [second, first])
        assert repo.get_requirements("alice", "case-1") == [second, first]
        values = repo.get_requirements("alice", "case-1")
        values[0].text = "Mutated"
        assert repo.get_requirements("alice", "case-1")[0] == second
        repo.save_requirements("alice", "case-1", [first])
        assert repo.get_requirements("alice", "case-1") == [first]
        repo.save_requirements("alice", "case-1", [])
        assert repo.get_requirements("alice", "case-1") == []

    def test_findings_replace_round_trip_and_detach(self, storage):
        repo, _ = storage
        repo.save_case("alice", make_case())
        values = [finding("z-first"), finding("a-second")]
        repo.save_findings("alice", "case-1", values)
        assert repo.get_findings("alice", "case-1") == values
        detached = repo.get_findings("alice", "case-1")
        detached[0].evidence[0].excerpt = "Changed"
        assert repo.get_findings("alice", "case-1") == values
        values[0].review, values[0].edited_text = Decision.ACCEPT, None
        repo.save_findings("alice", "case-1", values[:1])
        assert repo.get_findings("alice", "case-1") == values[:1]
        repo.save_findings("alice", "case-1", [])
        assert repo.get_findings("alice", "case-1") == []

    def test_distinct_jobs_and_nested_budget_detachment(self, storage):
        repo, _ = storage
        repo.save_case("alice", make_case())
        values = [job(), job("job-2", 2)]
        values[0].budget = {"nested": {"tasks": [1, 2]}}
        values[1].budget = None
        for value in values:
            repo.save_job("alice", value)
        assert repo.get_jobs("alice", "case-1") == values
        repo.get_jobs("alice", "case-1")[0].budget["nested"]["tasks"].append(3)
        assert repo.get_jobs("alice", "case-1") == values

    @pytest.mark.parametrize("partial", [False, True])
    def test_service_run_and_decision(self, storage, partial):
        repo, _ = storage
        ids = iter(["case-1", "job-1"])
        service = ReviewCaseService(
            repo, FakeReviewEngine(skip_budget=partial), clock=lambda: NOW,
            id_factory=lambda: next(ids),
        )
        service.create_case("alice", "Audit", "Check policy.")
        service.propose_requirements("case-1", "alice")
        service.confirm_requirements("case-1", "alice")
        result = service.start_run("case-1", "alice", {"tasks": 1})
        assert service._case("case-1", "alice").status == (
            CaseStatus.PARTIAL if partial else CaseStatus.COMPLETE
        )
        assert repo.get_jobs("alice", "case-1")[-1].state == (
            JobState.PARTIAL if partial else JobState.SUCCEEDED
        )
        decided = service.decide_finding("case-1", "alice", result[0].id, Decision.EDIT, "Reviewed")
        assert decided.verdict == result[0].verdict
        assert "Decision: EDIT" in service.export_markdown("case-1", "alice")


class DatabaseBehavior(RepositoryBehavior):
    @staticmethod
    def seeded(storage):
        repo, factory = storage
        repo.save_case("alice", make_case())
        repo.save_job("alice", job())
        return repo, PostgresCaseRepository(factory, "alice")

    def test_save_job_upserts_terminal_state(self, storage):
        repo, _ = storage
        repo.save_case("alice", make_case())
        value = job()
        repo.save_job("alice", value)
        value.state, value.started_at, value.finished_at = JobState.SUCCEEDED, NOW, NOW
        repo.save_job("alice", value)
        assert repo.get_jobs("alice", "case-1") == [value]
        assert repo.get_job("alice", value.id) == value
        assert repo.get_job("bob", value.id) is None

    def test_colliding_ids_cannot_overwrite_another_owner(self, storage):
        repo, _ = self.seeded(storage)
        repo.save_case("bob", make_case("case-2", "bob"))
        with pytest.raises(IntegrityError):
            repo.save_case("bob", make_case("case-1", "bob"))
        with pytest.raises(IntegrityError):
            repo.save_job("bob", job(case_id="case-2"))
        assert repo.get_case("alice", "case-1").owner_user_id == "alice"
        assert repo.get_job("alice", "job-1").case_id == "case-1"

    def test_requirement_uniqueness_failure_rolls_back_replace(self, storage):
        repo, _ = self.seeded(storage)
        repo.save_requirements("alice", "case-1", [requirement()])
        with pytest.raises(IntegrityError):
            repo.save_requirements("alice", "case-1", [requirement(), requirement("duplicate-order")])
        assert repo.get_requirements("alice", "case-1") == [requirement()]

    @pytest.mark.parametrize("resource", ["requirements", "findings"])
    def test_cross_case_values_are_rejected(self, storage, resource):
        repo, _ = self.seeded(storage)
        value = requirement() if resource == "requirements" else finding()
        value.case_id = "case-2"
        with pytest.raises(ValueError, match="case mismatch"):
            getattr(repo, f"save_{resource}")("alice", "case-1", [value])

    def test_claim_heartbeat_expiry_release_and_finish(self, storage):
        repo, queue = self.seeded(storage)
        claimed = queue.claim_next_job("worker-1", 10, NOW)
        assert claimed["id"] == "job-1" and claimed["state"] == "RUNNING"
        assert claimed["attempt"] == 1 and claimed["started_at"] == NOW
        assert claimed["lease_expires_at"] == NOW + timedelta(seconds=10)
        assert queue.claim_next_job("worker-2", 10, NOW) is None
        assert not queue.heartbeat("job-1", "wrong-worker", 10, NOW)
        assert queue.heartbeat("job-1", "worker-1", 20, NOW + timedelta(seconds=5))
        assert queue.list_expired_running_jobs(NOW + timedelta(seconds=24)) == []
        expired = queue.list_expired_running_jobs(NOW + timedelta(seconds=25))
        assert [row["id"] for row in expired] == ["job-1"]
        assert not queue.heartbeat("job-1", "worker-1", 10, NOW + timedelta(seconds=25))
        assert not queue.finish_job("job-1", "worker-1", "SUCCEEDED", NOW + timedelta(seconds=25))
        assert not queue.release_job("job-1", "wrong-worker", NOW)
        assert queue.release_job("job-1", "worker-1", NOW + timedelta(seconds=26))
        reclaimed = queue.claim_next_job("worker-2", 10, NOW + timedelta(seconds=27))
        assert reclaimed["attempt"] == 2 and reclaimed["started_at"] == NOW
        assert not queue.release_job("job-1", "worker-1", NOW + timedelta(seconds=28))
        assert queue.finish_job("job-1", "worker-2", "FAILED", NOW + timedelta(seconds=28), "failed")
        assert repo.get_job("alice", "job-1").finished_at == NOW + timedelta(seconds=28)
        assert queue.list_expired_running_jobs(NOW + timedelta(days=1)) == []
        assert not queue.release_job("job-1", "worker-2", NOW + timedelta(seconds=29))

    def test_queue_and_events_are_owner_scoped(self, storage):
        repo, queue = self.seeded(storage)
        factory = storage[1]
        foreign = PostgresCaseRepository(factory, "bob")
        assert foreign.claim_next_job("worker", 10, NOW) is None
        assert foreign.read_events("job-1", 0) == []
        with pytest.raises(KeyError):
            foreign.append_event("job-1", "job.started", {}, NOW)
        queue.claim_next_job("worker", 10, NOW)
        assert not foreign.heartbeat("job-1", "worker", 10, NOW)
        assert not foreign.release_job("job-1", "worker", NOW)
        assert not foreign.finish_job("job-1", "worker", "SUCCEEDED", NOW)
        assert foreign.list_expired_running_jobs(NOW + timedelta(seconds=10)) == []
        assert repo.read_events("job-1", 0, owner_user_id="alice") == []
        with pytest.raises(ValueError, match="owner_user_id is required"):
            repo.read_events("job-1", 0)
        with pytest.raises(ValueError, match="owner mismatch"):
            queue.read_events("job-1", 0, owner_user_id="bob")

    def test_event_sequences_replay_detachment_and_rollback(self, storage):
        _, queue = self.seeded(storage)
        assert queue.append_event("job-1", "job.started", {"nested": [1]}, NOW)["seq"] == 1
        with pytest.raises((StatementError, TypeError)):  # SQLAlchemy wraps on SQLite; psycopg raises TypeError directly
            queue.append_event("job-1", "invalid", {"not_json": object()}, NOW)
        assert queue.append_event("job-1", "job.done", {}, NOW)["seq"] == 2
        rows = queue.read_events("job-1", 0)
        assert [row["seq"] for row in rows] == [1, 2]
        assert rows[0]["ts"] == NOW
        rows[0]["data"]["nested"].append(2)
        assert queue.read_events("job-1", 0)[0]["data"] == {"nested": [1]}
        assert [row["seq"] for row in queue.read_events("job-1", 1)] == [2]
        assert queue.read_events("job-1", 2) == []
        with pytest.raises(KeyError):
            queue.append_event("missing", "job.done", {}, NOW)

    def test_concurrent_appends_across_repository_instances(self, storage):
        _, queue = self.seeded(storage)
        factory = storage[1]
        barrier = Barrier(4)

        def append(worker):
            local = PostgresCaseRepository(factory, "alice")
            barrier.wait(timeout=10)
            return [local.append_event("job-1", "progress", {"worker": worker, "n": n}, NOW)["seq"]
                    for n in range(8)]

        with ThreadPoolExecutor(max_workers=4) as pool:
            sequences = list(pool.map(append, range(4)))
        assert sorted(seq for batch in sequences for seq in batch) == list(range(1, 33))
        assert [row["seq"] for row in queue.read_events("job-1", 0)] == list(range(1, 33))

    def test_concurrent_claims_never_duplicate_a_job(self, storage):
        repo, _ = self.seeded(storage)
        factory = storage[1]
        for index in range(2, 5):
            repo.save_job("alice", job(f"job-{index}", index))
        barrier = Barrier(4)

        def claim(worker):
            local = PostgresCaseRepository(factory, "alice")
            barrier.wait(timeout=10)
            return local.claim_next_job(f"worker-{worker}", 10, NOW)

        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(claim, range(4)))
        assert {row["id"] for row in claimed} == {f"job-{n}" for n in range(1, 5)}

    def test_case_delete_cascades_only_its_children(self, storage):
        repo, queue = self.seeded(storage)
        repo.save_case("bob", make_case("case-2", "bob"))
        repo.save_job("bob", job("job-2", case_id="case-2"))
        repo.save_requirements("alice", "case-1", [requirement()])
        repo.save_findings("alice", "case-1", [finding()])
        queue.append_event("job-1", "progress", {}, NOW)
        with storage[1].begin() as db:
            db.execute(delete(ReviewCaseRecord).where(
                ReviewCaseRecord.owner_user_id == "alice", ReviewCaseRecord.id == "case-1",
            ))
        assert repo.get_requirements("alice", "case-1") == []
        assert repo.get_findings("alice", "case-1") == []
        assert repo.get_jobs("alice", "case-1") == []
        assert queue.read_events("job-1", 0) == []
        with storage[1]() as db:
            assert db.scalar(select(func.count()).select_from(ReviewRunEventRecord)) == 0
        assert repo.get_job("bob", "job-2") is not None


class TestMemoryRepository(RepositoryBehavior):
    backend = "memory"


class TestSQLiteRepository(DatabaseBehavior):
    backend = "sqlite"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
class TestPostgresRepository(DatabaseBehavior):
    backend = "postgresql"


@pytest.mark.xfail(strict=False, reason="SUSPECTED DEFECT: InMemoryCaseRepository.save_job appends duplicate IDs instead of updating the service's job")
def test_memory_save_job_should_update_existing_job():
    repo = InMemoryCaseRepository()
    repo.save_case("alice", make_case())
    value = job()
    repo.save_job("alice", value)
    value.state = JobState.SUCCEEDED
    repo.save_job("alice", value)
    assert repo.get_jobs("alice", "case-1") == [value]


def load_migration():
    path = BACKEND / "migrations" / "versions" / "20261114_05_review_cases.py"
    spec = importlib.util.spec_from_file_location("review_cases_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_exactly_one_head_and_expected_predecessor():
    scripts = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert scripts.get_heads() == ["20261114_05"]
    assert scripts.get_revision("20261114_05").down_revision == "20261111_04"


def test_migration_upgrade_matches_models_and_downgrade_is_review_only(monkeypatch):
    migration = load_migration()
    engine = sqlite_engine()
    try:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            monkeypatch.setattr(migration, "op", operations)
            migration.upgrade()
            assert set(inspect(connection).get_table_names()) == {table.name for table in TABLES}
            differences = compare_metadata(MigrationContext.configure(connection, opts={
                "include_object": lambda obj, name, type_, reflected, compare_to:
                    type_ != "table" or name.startswith("review_"),
                "compare_type": True,
                "compare_server_default": True,
            }), Base.metadata)
            assert differences == []
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()


def test_migration_compiles_postgresql_ddl_without_connection(monkeypatch):
    migration = load_migration()
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={
        "as_sql": True, "output_buffer": output,
    })
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    migration.downgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE review_") == 5
    assert sql.count("DROP TABLE review_") == 5
    assert "JSONB" in sql and "TIMESTAMP WITH TIME ZONE" in sql
    assert "ON DELETE CASCADE" in sql
    assert "ix_review_run_jobs_state_lease" in sql
