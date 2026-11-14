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

from app.review.schemas import CaseStatus, Finding, JobState, Requirement, ReviewCase, RunJob
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
    def __init__(self, session_factory, owner_user_id: str | None = None, *, route_decider=None):
        self.session_factory = session_factory
        self.owner_user_id = owner_user_id
        self.route_decider = route_decider

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
               ("id", "owner_user_id", "title", "status", "request_text", "source_ids", "kind")},
            old_source_id=(row.meta or {}).get("old_source_id"),
            new_source_id=(row.meta or {}).get("new_source_id"),
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
            source_pair = {key: values.pop(key) for key in ("old_source_id", "new_source_id")}
            values["meta"] = source_pair if case.kind == "spec_change" else None
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

    @staticmethod
    def _put_finding(db, owner, case_id, value):
        if value.case_id != case_id:
            raise ValueError("case mismatch")
        row = db.scalar(select(FindingRow).where(
            FindingRow.owner_user_id == owner, FindingRow.case_id == case_id,
            FindingRow.requirement_id == value.requirement_id,
        ).with_for_update())
        if row is None:
            db.add(FindingRow(**value.model_dump(mode="json"), owner_user_id=owner,
                              created_at=datetime.now(timezone.utc)))
        else:
            for key, item in value.model_dump(mode="json").items():
                setattr(row, key, item)

    def save_finding(self, owner_user_id, case_id, value):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            self._require_case(db, owner, case_id)
            self._put_finding(db, owner, case_id, value)

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

    def claim_next_job(self, lease_owner, lease_seconds, now, *, owner_user_id=None,
                       all_owners=False, prepare_case=False):
        """Claim the oldest queued job for this owner; expiry requires explicit release."""
        owner = None if all_owners and self.owner_user_id is None else self._owner(owner_user_id)
        expires = self._lease_end(lease_owner, lease_seconds, now)
        with self._transaction() as db:
            query = (select(Job) if owner is None else self._job_query(owner))
            query = query.where(Job.state == JobState.QUEUED).order_by(
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
            if prepare_case:
                case = self._require_case(db, row.owner_user_id, row.case_id)
                case.status, case.updated_at = CaseStatus.RUNNING.value, _utc(now)
                if row.attempt == 1:
                    db.execute(delete(FindingRow).where(
                        FindingRow.owner_user_id == row.owner_user_id, FindingRow.case_id == row.case_id,
                    ))
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

    def finish_job(self, job_id, lease_owner, state, now, error=None, *, owner_user_id=None,
                   event_type=None, update_case=False):
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
            if event_type:
                self._append_event(db, row, event_type, {"message": error} if error else {}, now)
            if update_case:
                case = self._require_case(db, owner, row.case_id)
                case.status = (CaseStatus.COMPLETE.value if state == JobState.SUCCEEDED else
                               CaseStatus.FAILED.value if state == JobState.FAILED else
                               CaseStatus.PARTIAL.value)
                case.updated_at = _utc(now)
            return True

    def list_expired_running_jobs(self, now, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [self._snapshot(row) for row in db.scalars(self._job_query(owner).where(
                Job.state == JobState.RUNNING, Job.lease_expires_at <= _utc(now),
            ).order_by(Job.lease_expires_at, Job.id))]

    def append_event(self, job_id, type, data, ts, *, owner_user_id=None, lease_owner=None):
        """Lock the parent job, allocate max+1, and insert in one transaction."""
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            job = (self._leased_job(db, owner, job_id, lease_owner, ts) if lease_owner is not None
                   else db.scalar(self._job_query(owner, job_id).with_for_update()))
            if job is None:
                if lease_owner is not None:
                    return None
                raise KeyError(job_id)
            return self._append_event(db, job, type, data, ts)

    @classmethod
    def _append_event(cls, db, job, type, data, ts):
        last = db.scalar(select(func.max(Event.seq)).where(Event.job_id == job.id))
        row = Event(job_id=job.id, seq=(last or 0) + 1, ts=_utc(ts), type=type, data=deepcopy(data))
        db.add(row)
        db.flush()
        return cls._snapshot(row)

    def read_events(self, job_id, after_seq=0, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            return [self._snapshot(row) for row in db.scalars(select(Event).join(
                Job, Event.job_id == Job.id,
            ).where(Job.owner_user_id == owner, Event.job_id == job_id, Event.seq > after_seq)
                .order_by(Event.seq))]

    def job_record(self, job_id):
        """Internal worker lookup; HTTP callers must authorize with get_job first."""
        with self._transaction() as db:
            query = select(Job).where(Job.id == job_id)
            if self.owner_user_id is not None:
                query = query.where(Job.owner_user_id == self.owner_user_id)
            row = db.scalar(query)
            if row is None:
                raise KeyError(job_id)
            return self._snapshot(row)

    def enqueue_job(self, owner, case_id, job_id, budget):
        owner = self._owner(owner)
        with self._transaction() as db:
            case = self._require_case(db, owner, case_id)
            jobs = self._job_query(owner).where(Job.case_id == case_id)
            if db.scalar(jobs.where(Job.state.in_(["QUEUED", "RUNNING"]))) is not None:
                raise ValueError("case has an active run")
            last = db.scalar(select(func.max(Job.seq)).where(
                Job.owner_user_id == owner, Job.case_id == case_id,
            ))
            job = Job(id=job_id, case_id=case_id, owner_user_id=owner,
                      state="QUEUED", seq=(last or 0) + 1, budget=deepcopy(budget))
            db.add(job)
            if self.route_decider is not None:
                db.flush()
                count = db.scalar(select(func.count()).select_from(RequirementRow).where(
                    RequirementRow.case_id == case_id, RequirementRow.owner_user_id == owner,
                ))
                self._append_event(db, job, "route.decided",
                                   self.route_decider(self._case_entity(case), count), _utc(job.created_at))

    def checkpoint_finding(self, job_id, lease_owner, now, finding, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            row = self._leased_job(db, owner, job_id, lease_owner, now)
            if row is None:
                return False
            self._put_finding(db, owner, row.case_id, finding)
            self._append_event(db, row, "finding.created", finding.model_dump(mode="json"), now)
            return True

    def cancel_job(self, job_id, now, *, owner_user_id=None):
        owner = self._owner(owner_user_id)
        with self._transaction() as db:
            row = db.scalar(self._job_query(owner, job_id).with_for_update())
            if row is None:
                raise KeyError(job_id)
            if JobState(row.state) in _TERMINAL:
                return
            row.state, row.finished_at = JobState.CANCELLED.value, _utc(now)
            row.lease_owner = row.lease_expires_at = None
            self._append_event(db, row, "job.cancelled", {}, now)
            case = self._require_case(db, owner, row.case_id)
            case.status, case.updated_at = CaseStatus.PARTIAL.value, _utc(now)

    def recover_jobs(self, now, max_attempts=3):
        """Lock expired leases atomically; repeated/multi-process recovery is safe."""
        with self._transaction() as db:
            query = select(Job).where(Job.state == "RUNNING", Job.lease_expires_at <= _utc(now))
            if self.owner_user_id is not None:
                query = query.where(Job.owner_user_id == self.owner_user_id)
            query = query.with_for_update(skip_locked=True)
            recovered = []
            for row in db.scalars(query):
                row.lease_owner = row.lease_expires_at = None
                if row.attempt >= max_attempts:
                    row.state, row.finished_at = "FAILED", _utc(now)
                    row.error = "Lease expired after maximum attempts"
                    self._append_event(db, row, "job.failed", {"message": row.error}, now)
                    case = self._require_case(db, row.owner_user_id, row.case_id)
                    case.status, case.updated_at = "FAILED", _utc(now)
                else:
                    row.state = "QUEUED"
                recovered.append(row.id)
            return recovered
