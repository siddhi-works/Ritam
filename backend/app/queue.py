"""Durable job queue in Postgres, no Redis needed.

- A job is claimed with SELECT ... FOR UPDATE SKIP LOCKED, so two workers never take the same job.
- A running job holds a lease (LEASE) that its worker renews every HEARTBEAT. If the process dies
  (deploy, restart, crash), the lease runs out and the job is claimed again.
- Only a run that raised an error uses up an attempt; a run cut short by a restart doesn't. A
  failed attempt is retried with growing waits; after max_attempts the job's failure hook runs
  (for a report: mark it failed with the reason) and the job stays failed. A job that keeps
  getting cut short (say it crashes the process) is stopped after MAX_STARTS_PER_ATTEMPT tries.
- Finished jobs are deleted after KEEP_FINISHED, so the table stays small.
- The worker never polls the database while idle: Neon's free tier suspends an idle database, and
  polling would keep it awake all month. It wakes on new work in this process, on its own retry
  timers, and once at startup to pick up work a dead process left behind.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, JobStatus

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=2)
HEARTBEAT = timedelta(seconds=40)
BACKOFF = (timedelta(seconds=30), timedelta(minutes=2), timedelta(minutes=8))
MAX_STARTS_PER_ATTEMPT = 3
KEEP_FINISHED = timedelta(days=14)
STOPPED = "Stopped after being interrupted too many times."

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Claimed:
    id: uuid.UUID
    name: str
    args: list[str]
    attempts: int
    max_attempts: int


class JobStore(Protocol):
    async def add(self, name: str, args: list[str], max_attempts: int) -> uuid.UUID: ...
    async def claim(self, worker: str, now: datetime) -> Claimed | None: ...
    async def renew(self, job_id: uuid.UUID, worker: str, now: datetime) -> bool: ...
    async def done(self, job_id: uuid.UUID, worker: str, now: datetime) -> None: ...
    async def fail(self, job: Claimed, worker: str, now: datetime, error: str) -> bool: ...
    async def next_wake(self, worker: str) -> datetime | None: ...
    async def prune(self, before: datetime) -> int: ...


def retry_at(attempts: int, now: datetime) -> datetime:
    return now + BACKOFF[min(attempts, len(BACKOFF)) - 1]


class PgJobStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]):
        self._sm = sessionmaker

    async def add(self, name: str, args: list[str], max_attempts: int) -> uuid.UUID:
        async with self._sm() as s:
            job = Job(name=name, args=args, max_attempts=max_attempts, status=JobStatus.QUEUED)
            s.add(job)
            await s.commit()
            return job.id

    async def claim(self, worker: str, now: datetime) -> Claimed | None:
        async with self._sm() as s, s.begin():
            row = await s.scalar(
                select(Job)
                .where(
                    or_(
                        (Job.status == JobStatus.QUEUED) & (Job.run_after <= now),
                        (Job.status == JobStatus.RUNNING) & (Job.lease_until < now),  # dead worker
                    )
                )
                .order_by(Job.run_after)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            if row.starts >= row.max_attempts * MAX_STARTS_PER_ATTEMPT:
                row.status, row.finished_at, row.last_error = JobStatus.FAILED, now, STOPPED
                return None  # its report is marked failed by startup recovery
            row.status, row.locked_by, row.lease_until = JobStatus.RUNNING, worker, now + LEASE
            row.starts += 1
            return Claimed(row.id, row.name, list(row.args), row.attempts + 1, row.max_attempts)

    async def renew(self, job_id: uuid.UUID, worker: str, now: datetime) -> bool:
        async with self._sm() as s, s.begin():
            res = await s.execute(
                update(Job)
                .where(Job.id == job_id, Job.locked_by == worker, Job.status == JobStatus.RUNNING)
                .values(lease_until=now + LEASE)
            )
            return bool(res.rowcount)  # type: ignore[attr-defined]

    async def done(self, job_id: uuid.UUID, worker: str, now: datetime) -> None:
        async with self._sm() as s, s.begin():
            await s.execute(
                update(Job)
                .where(Job.id == job_id, Job.locked_by == worker)
                .values(status=JobStatus.DONE, finished_at=now, lease_until=None)
            )

    async def fail(self, job: Claimed, worker: str, now: datetime, error: str) -> bool:
        """Record a failed attempt. True when it was the last one."""
        final = job.attempts >= job.max_attempts
        async with self._sm() as s, s.begin():
            await s.execute(
                update(Job)
                .where(Job.id == job.id, Job.locked_by == worker)
                .values(
                    attempts=job.attempts,
                    status=JobStatus.FAILED if final else JobStatus.QUEUED,
                    run_after=now if final else retry_at(job.attempts, now),
                    last_error=error[:2000],
                    lease_until=None,
                    finished_at=now if final else None,
                )
            )
        return final

    async def prune(self, before: datetime) -> int:
        async with self._sm() as s, s.begin():
            res = await s.execute(
                delete(Job).where(
                    Job.status.in_([JobStatus.DONE, JobStatus.FAILED]), Job.finished_at < before
                )
            )
            return int(res.rowcount or 0)  # type: ignore[attr-defined]

    async def next_wake(self, worker: str) -> datetime | None:
        """Earliest time something may need doing: a queued job's run time, or the lease end of a
        job another worker holds (in case that worker died)."""
        async with self._sm() as s:
            return await s.scalar(
                select(
                    func.least(
                        func.min(Job.run_after).filter(Job.status == JobStatus.QUEUED),
                        func.min(Job.lease_until).filter(
                            Job.status == JobStatus.RUNNING, Job.locked_by != worker
                        ),
                    )
                )
            )


async def _persist(what: str, write: Callable[[], Awaitable[Any]], tries: int = 3) -> Any:
    """Bookkeeping writes after a job runs, retried through a brief database hiccup."""
    for n in range(tries):
        try:
            return await write()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - logged; the lease is the last safety net
            if n == tries - 1:
                log.error("job queue could not %s: %s", what, type(exc).__name__)
                return None
            await asyncio.sleep(2**n)
    return None


Handler = Callable[..., Awaitable[Any]]
OnGiveUp = Callable[[str, list[str], str], Awaitable[None]]


class Worker:
    """Runs jobs from a JobStore inside this process, `concurrency` at a time."""

    def __init__(
        self,
        store: JobStore,
        handlers: dict[str, Handler],
        *,
        on_give_up: OnGiveUp | None = None,
        concurrency: int = 2,
        clock: Clock = utcnow,
        heartbeat: timedelta = HEARTBEAT,
    ):
        self.store, self.handlers, self.on_give_up = store, handlers, on_give_up
        self.id = f"w-{uuid.uuid4().hex[:12]}"
        self._clock, self._heartbeat = clock, heartbeat
        self._gate = asyncio.Semaphore(concurrency)
        self._wake = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._loop: asyncio.Task[None] | None = None

    async def enqueue(self, name: str, *args: str, max_attempts: int = 3) -> uuid.UUID:
        if name not in self.handlers:
            raise KeyError(name)
        jid = await self.store.add(name, list(args), max_attempts)
        self._wake.set()
        return jid

    def start(self) -> None:
        self._loop = asyncio.create_task(self._run(), name="job-worker")

    async def stop(self) -> None:
        """Stop taking work. Running jobs are cancelled; their leases expire and the next process
        picks them up again."""
        pending = {t for t in [self._loop, *self._tasks] if t}
        for t in pending:
            t.cancel()
        if pending:
            # Never hold up a shutdown on a slow or unreachable database: anything unfinished is
            # picked up again when its lease runs out.
            await asyncio.wait(pending, timeout=2)

    async def run_once(self) -> int:
        """Claim and start every job that is ready now, within the concurrency limit. Returns how
        many were started. (The loop calls this; tests call it directly.)"""
        started = 0
        while not self._gate.locked():
            job = await self.store.claim(self.id, self._clock())
            if job is None:
                break
            await self._gate.acquire()
            task = asyncio.create_task(self._execute(job))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            started += 1
        return started

    async def _run(self) -> None:
        try:
            removed = await self.store.prune(self._clock() - KEEP_FINISHED)
            if removed:
                log.info("pruned finished jobs", extra={"count": removed})
        except Exception as exc:  # noqa: BLE001 - housekeeping only
            log.warning("job pruning skipped: %s", type(exc).__name__)
        while True:
            wake: datetime | None = None
            try:
                await self.run_once()
                if not self._gate.locked():  # all slots busy: only a finishing job matters
                    wake = await self.store.next_wake(self.id)
            except Exception as exc:  # noqa: BLE001 - e.g. database asleep: try again later
                log.warning("job worker could not reach the queue: %s", type(exc).__name__)
                wake = self._clock() + timedelta(seconds=30)
            self._wake.clear()
            # No timeout when nothing is scheduled: an idle worker sends no queries at all.
            timeout = None if wake is None else max(0.5, (wake - self._clock()).total_seconds())
            try:
                await asyncio.wait_for(self._wake.wait(), timeout)
            except TimeoutError:
                pass

    async def _execute(self, job: Claimed) -> None:
        beat = asyncio.create_task(self._beat(job.id))
        try:
            await self.handlers[job.name](*job.args)
        except asyncio.CancelledError:
            raise  # shutting down: leave the lease to expire so the job is picked up again
        except Exception as exc:  # noqa: BLE001 - recorded on the job and retried
            error = f"{type(exc).__name__}: {exc}"
            final = await _persist(
                "record a failed attempt",
                lambda: self.store.fail(job, self.id, self._clock(), error),
            )
            log.warning(
                "job failed", extra={"job": job.name, "attempt": job.attempts, "final": final}
            )
            give_up = self.on_give_up
            if final and give_up is not None:
                await _persist("run the give-up step", lambda: give_up(job.name, job.args, error))
        else:
            # If this never lands, the lease runs out and the job runs again: retry first.
            await _persist(
                "mark the job done", lambda: self.store.done(job.id, self.id, self._clock())
            )
        finally:
            beat.cancel()
            self._gate.release()
            self._wake.set()  # a slot is free: look for more work

    async def _beat(self, job_id: uuid.UUID) -> None:
        while True:
            await asyncio.sleep(self._heartbeat.total_seconds())
            try:
                await self.store.renew(job_id, self.id, self._clock())
            except Exception as exc:  # noqa: BLE001 - a missed beat only shortens the lease
                log.warning("job lease renewal failed: %s", type(exc).__name__)
