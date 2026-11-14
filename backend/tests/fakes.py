"""Test doubles shared by several test modules."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.models import JobStatus
from app.queue import LEASE, MAX_STARTS_PER_ATTEMPT, STOPPED, Claimed, Clock, retry_at, utcnow


@dataclass
class _Row:
    name: str
    args: list[str]
    max_attempts: int
    status: JobStatus = JobStatus.QUEUED
    attempts: int = 0
    starts: int = 0
    finished_at: datetime | None = None
    run_after: datetime = field(default_factory=utcnow)
    locked_by: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None


class MemoryJobStore:
    """PgJobStore's behaviour in memory, with a controllable clock."""

    def __init__(self, clock: Clock = utcnow):
        self.rows: dict[uuid.UUID, _Row] = {}
        self._clock = clock

    async def add(self, name: str, args: list[str], max_attempts: int) -> uuid.UUID:
        jid = uuid.uuid4()
        self.rows[jid] = _Row(name, args, max_attempts, run_after=self._clock())
        return jid

    async def claim(self, worker: str, now: datetime) -> Claimed | None:
        ready = [
            (r.run_after, jid)
            for jid, r in self.rows.items()
            if (r.status == JobStatus.QUEUED and r.run_after <= now)
            or (r.status == JobStatus.RUNNING and r.lease_until is not None and r.lease_until < now)
        ]
        if not ready:
            return None
        jid = min(ready)[1]
        r = self.rows[jid]
        if r.starts >= r.max_attempts * MAX_STARTS_PER_ATTEMPT:
            r.status, r.finished_at, r.last_error = JobStatus.FAILED, now, STOPPED
            return None
        r.status = JobStatus.RUNNING
        r.locked_by = worker
        r.lease_until = now + LEASE
        r.starts += 1
        return Claimed(jid, r.name, list(r.args), r.attempts + 1, r.max_attempts)

    async def renew(self, job_id: uuid.UUID, worker: str, now: datetime) -> bool:
        r = self.rows[job_id]
        if r.locked_by != worker or r.status != JobStatus.RUNNING:
            return False
        r.lease_until = now + LEASE
        return True

    async def done(self, job_id: uuid.UUID, worker: str, now: datetime) -> None:
        r = self.rows[job_id]
        if r.locked_by == worker:
            r.status, r.lease_until, r.finished_at = JobStatus.DONE, None, now

    async def fail(self, job: Claimed, worker: str, now: datetime, error: str) -> bool:
        r = self.rows[job.id]
        final = job.attempts >= job.max_attempts
        if r.locked_by == worker:
            r.attempts = job.attempts
            r.status = JobStatus.FAILED if final else JobStatus.QUEUED
            r.finished_at = now if final else None
            r.run_after = now if final else retry_at(job.attempts, now)
            r.last_error, r.lease_until = error, None
        return final

    async def prune(self, before: datetime) -> int:
        old = [
            jid
            for jid, r in self.rows.items()
            if r.status in (JobStatus.DONE, JobStatus.FAILED)
            and r.finished_at is not None
            and r.finished_at < before
        ]
        for jid in old:
            del self.rows[jid]
        return len(old)

    async def next_wake(self, worker: str) -> datetime | None:
        times = [r.run_after for r in self.rows.values() if r.status == JobStatus.QUEUED]
        times += [
            r.lease_until
            for r in self.rows.values()
            if r.status == JobStatus.RUNNING and r.lease_until and r.locked_by != worker
        ]
        return min(times) if times else None
