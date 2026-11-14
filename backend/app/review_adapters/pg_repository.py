"""Owner-scoped review storage and leased job helpers.

Queue helpers require an owner, either bound at construction or supplied as the
``owner_user_id`` keyword. They return detached dictionaries (including lease
metadata); domain repository methods return domain entities. SQLite serializes
transactions per engine, including across repository instances sharing an
in-memory connection. PostgreSQL uses row locks for cross-process coordination.
"""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock, RLock
from weakref import WeakKeyDictionary

from sqlalchemy import delete, func, select

from app.review.schemas import Finding, JobState, Requirement, ReviewCase, RunJob
from app.storage.postgres.review_models import (
    ReviewCaseRecord as Case,
    ReviewFindingRecord as FindingRow,
    ReviewRequirementRecord as RequirementRow,
    ReviewRunEventRecord as Event,
    ReviewRunJobRecord as Job,
)


_sqlite_locks = WeakKeyDictionary()
_locks_guard = Lock()
_TERMINAL = {JobState.SUCCEEDED, JobState.PARTIAL, JobState.FAILED, JobState.CANCELLED}


def _utc(value):
    # SQLite drops timezone information; all adapter writes are normalized to UTC.
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class PostgresCaseRepository:
    def __init__(self, session_factory, owner_user_id: str | None = None):
        self.session_factory = session_factory
        self.owner_user_id = owner_user_id

    def _owner(self, owner):
        if self.owner_user_id is not None and owner is not None and owner != self.owner_user_id:
            raise ValueError("owner mismatch")
        owner = owner if owner is not None else self.owner_user_id
        if not owner:
            raise ValueError("owner_user_id is required")
        return owner

    @contextmanager
    def _transaction(self):
        with self.session_factory() as db:
            bind = db.get_bind()
            if bind.dialect.name == "sqlite":
                engine = getattr(bind, "engine", bind)
                with _locks_guard:
                    lock = _sqlite_locks.setdefault(engine, RLock())
            else:
                lock = nullcontext()
            with lock, db.begin():
                yield db

    @staticmethod
    def _case_query(owner, case_id):
        return select(Case).where(Case.owner_user_id == owner, Case.id == case_id)

    @classmethod
    def _require_case(cls, db, owner, case_id):
        row = db.scalar(cls._case_query(owner, case_id).with_for_update())
        if row is None:
            raise KeyError(case_id)
        return row

    @staticmethod
    def _job_query(owner, job_id=None):
        query = select(Job).where(Job.owner_user_id == owner)
        return query if job_id is None else query.where(Job.id == job_id)

    @staticmethod
    def _case_entity(row):
        return ReviewCase(
            **{key: deepcopy(getattr(row, key)) for key in
               ("id", "owner_user_id", "title", "status", "request_text", "source_ids")},
            created_at=_utc(row.created_at), updated_at=_utc(row.updated_at),
        )

    @staticmethod
    def _job_entity(row):
        return RunJob(
            **{key: deepcopy(getattr(row, key)) for key in
               ("id", "case_id", "state", "seq", "budget")},
            started_at=_utc(row.started_at), finished_at=_utc(row.finished_at),
        )

    @staticmethod
    def _snapshot(row):
        return {
            column.name: _utc(value) if isinstance(value, datetime) else deepcopy(value)
            for column in row.__table__.columns
            for value in [getattr(row, column.name)]
        }

    def save_case(self, owner_user_id: str, case: ReviewCase) -> None:
        owner = self._owner(owner_user_id)
        if owner != case.owner_user_id:
            raise ValueError("owner mismatch")
        with self._transaction() as db:
            row = db.scalar(self._case_query(owner, case.id).with_for_update())
            values = case.model_dump(mode="python")
            values.update(created_at=_utc(case.created_at), updated_at=_utc(case.updated_at))
            if row is None:
                # A foreign owner's colliding primary key fails without overwriting it.
                db.add(Case(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, deepcopy(value))

    def get_case(self, owner_user_id: str, case_id: str) -> ReviewCase | None:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            row = db.scalar(self._case_query(owner, case_id))
            return None if row is None else self._case_entity(row)

    def list_cases(self, owner_user_id: str) -> list[ReviewCase]:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [self._case_entity(row) for row in db.scalars(
                select(Case).where(Case.owner_user_id == owner).order_by(Case.created_at, Case.id)
            )]

    def save_requirements(self, owner_user_id: str, case_id: str, values: list[Requirement]) -> None:
        owner = self._owner(owner_user_id)
        if any(value.case_id != case_id for value in values):
            raise ValueError("case mismatch")
        with self._transaction() as db:
            self._require_case(db, owner, case_id)
            db.execute(delete(RequirementRow).where(
                RequirementRow.owner_user_id == owner, RequirementRow.case_id == case_id,
            ))
            db.add_all([
                RequirementRow(
                    id=value.id, case_id=case_id, owner_user_id=owner, text=value.text,
                    origin=value.origin.value, confirmed=value.confirmed, ord=value.order,
                ) for value in values
            ])

    def get_requirements(self, owner_user_id: str, case_id: str) -> list[Requirement]:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [Requirement(
                id=row.id, case_id=row.case_id, text=row.text, origin=row.origin,
                confirmed=row.confirmed, order=row.ord,
            ) for row in db.scalars(select(RequirementRow).where(
                RequirementRow.owner_user_id == owner, RequirementRow.case_id == case_id,
            ).order_by(RequirementRow.ord))]

    def save_findings(self, owner_user_id: str, case_id: str, values: list[Finding]) -> None:
        owner = self._owner(owner_user_id)
        if any(value.case_id != case_id for value in values):
            raise ValueError("case mismatch")
        with self._transaction() as db:
            self._require_case(db, owner, case_id)
            db.execute(delete(FindingRow).where(
                FindingRow.owner_user_id == owner, FindingRow.case_id == case_id,
            ))
            now = datetime.now(timezone.utc)
            db.add_all([
                FindingRow(
                    **value.model_dump(mode="json"), owner_user_id=owner,
                    created_at=now + timedelta(microseconds=index),
                ) for index, value in enumerate(values)
            ])

    def get_findings(self, owner_user_id: str, case_id: str) -> list[Finding]:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [Finding(**{key: deepcopy(getattr(row, key)) for key in Finding.model_fields})
                    for row in db.scalars(select(FindingRow).where(
                        FindingRow.owner_user_id == owner, FindingRow.case_id == case_id,
                    ).order_by(FindingRow.created_at, FindingRow.id))]

    def save_job(self, owner_user_id: str, job: RunJob) -> None:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            self._require_case(db, owner, job.case_id)
            row = db.scalar(self._job_query(owner, job.id).with_for_update())
            values = job.model_dump(mode="python")
            values.update(started_at=_utc(job.started_at), finished_at=_utc(job.finished_at))
            if row is None:
                db.add(Job(**values, owner_user_id=owner))
            else:
                if row.case_id != job.case_id:
                    raise ValueError("case mismatch")
                for key, value in values.items():
                    setattr(row, key, deepcopy(value))
                if job.state in _TERMINAL:
                    row.lease_owner = row.lease_expires_at = None

    def get_job(self, owner_user_id: str, job_id: str) -> RunJob | None:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            row = db.scalar(self._job_query(owner, job_id))
            return None if row is None else self._job_entity(row)

    def get_jobs(self, owner_user_id: str, case_id: str) -> list[RunJob]:
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [self._job_entity(row) for row in db.scalars(
                self._job_query(owner).where(Job.case_id == case_id).order_by(Job.seq, Job.id)
            )]

    @staticmethod
    def _lease_end(lease_owner, lease_seconds, now):
        if not lease_owner or lease_seconds <= 0:
            raise ValueError("lease owner and positive lease_seconds are required")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return _utc(now) + timedelta(seconds=lease_seconds)

    def claim_next_job(self, lease_owner, lease_seconds, now, *, owner_user_id=None):
        """Claim the oldest queued job for this owner; expiry requires explicit release."""
        owner = self._owner(owner_user_id)
        expires = self._lease_end(lease_owner, lease_seconds, now)
        with self._transaction() as db:
            query = self._job_query(owner).where(Job.state == JobState.QUEUED).order_by(
                Job.created_at, Job.seq, Job.id,
            ).limit(1)
            if db.get_bind().dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = db.scalar(query)
            if row is None:
                return None
            row.state = JobState.RUNNING.value
            row.attempt += 1
            row.lease_owner, row.lease_expires_at = lease_owner, expires
            row.heartbeat_at = _utc(now)
            row.started_at = row.started_at or _utc(now)
            row.finished_at = row.error = None
            return self._snapshot(row)

    @classmethod
    def _leased_job(cls, db, owner, job_id, lease_owner, now):
        return db.scalar(cls._job_query(owner, job_id).where(
            Job.state == JobState.RUNNING, Job.lease_owner == lease_owner,
            Job.lease_expires_at > _utc(now),
        ).with_for_update())

    def heartbeat(self, job_id, lease_owner, lease_seconds, now, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        expires = self._lease_end(lease_owner, lease_seconds, now)
        with self._transaction() as db:
            row = self._leased_job(db, owner, job_id, lease_owner, now)
            if row is None:
                return False
            row.heartbeat_at, row.lease_expires_at = _utc(now), expires
            return True

    def release_job(self, job_id, lease_owner, now, *, owner_user_id=None):
        """Requeue a lease held by this worker, including an expired lease.

        The holder check fences a stale worker after another worker has claimed it.
        """
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            row = db.scalar(self._job_query(owner, job_id).where(
                Job.state == JobState.RUNNING, Job.lease_owner == lease_owner,
            ).with_for_update())
            if row is None:
                return False
            row.state = JobState.QUEUED.value
            row.lease_owner = row.lease_expires_at = None
            row.heartbeat_at = _utc(now)
            return True

    def finish_job(self, job_id, lease_owner, state, now, error=None, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        state = JobState(state)
        if state not in _TERMINAL:
            raise ValueError("terminal job state required")
        with self._transaction() as db:
            row = self._leased_job(db, owner, job_id, lease_owner, now)
            if row is None:
                return False
            row.state, row.finished_at, row.error = state.value, _utc(now), error
            row.lease_owner = row.lease_expires_at = None
            return True

    def list_expired_running_jobs(self, now, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [self._snapshot(row) for row in db.scalars(self._job_query(owner).where(
                Job.state == JobState.RUNNING, Job.lease_expires_at <= _utc(now),
            ).order_by(Job.lease_expires_at, Job.id))]

    def append_event(self, job_id, type, data, ts, *, owner_user_id=None):
        """Lock the parent job, allocate max+1, and insert in one transaction."""
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            if db.scalar(self._job_query(owner, job_id).with_for_update()) is None:
                raise KeyError(job_id)
            last = db.scalar(select(func.max(Event.seq)).join(Job, Event.job_id == Job.id).where(
                Job.owner_user_id == owner, Event.job_id == job_id,
            ))
            row = Event(job_id=job_id, seq=(last or 0) + 1, ts=_utc(ts), type=type, data=deepcopy(data))
            db.add(row)
            db.flush()
            return self._snapshot(row)

    def read_events(self, job_id, after_seq=0, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [self._snapshot(row) for row in db.scalars(select(Event).join(
                Job, Event.job_id == Job.id,
            ).where(Job.owner_user_id == owner, Event.job_id == job_id, Event.seq > after_seq)
                .order_by(Event.seq))]
