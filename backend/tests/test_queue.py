import asyncio
from datetime import UTC, datetime, timedelta

from app.models import JobStatus
from app.queue import LEASE, Worker
from tests.fakes import MemoryJobStore


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 14, tzinfo=UTC)

    def __call__(self):
        return self.now


async def _drain(w: Worker):
    while w._tasks:
        await asyncio.gather(*list(w._tasks), return_exceptions=True)


async def test_job_runs_and_is_marked_done():
    clock, ran = Clock(), []
    store = MemoryJobStore(clock)

    async def job(x):
        ran.append(x)

    w = Worker(store, {"j": job}, clock=clock)
    await w.enqueue("j", "a")
    assert await w.run_once() == 1
    await _drain(w)
    assert ran == ["a"] and next(iter(store.rows.values())).status == JobStatus.DONE


async def test_failure_is_retried_then_gives_up_once():
    clock, gave_up = Clock(), []
    store = MemoryJobStore(clock)

    async def boom():
        raise RuntimeError("down")

    async def give_up(name, args, error):
        gave_up.append(error)

    w = Worker(store, {"j": boom}, clock=clock, on_give_up=give_up)
    await w.enqueue("j", max_attempts=2)
    await w.run_once()
    await _drain(w)
    row = next(iter(store.rows.values()))
    assert row.status == JobStatus.QUEUED and gave_up == []
    assert await w.run_once() == 0  # waits for the retry time
    clock.now += timedelta(minutes=1)
    await w.run_once()
    await _drain(w)
    assert row.status == JobStatus.FAILED and gave_up == ["RuntimeError: down"]


async def test_a_job_left_by_a_dead_worker_runs_again_after_its_lease():
    clock, ran = Clock(), []
    store = MemoryJobStore(clock)

    async def job():
        ran.append(1)

    dead = Worker(store, {"j": job}, clock=clock)
    await dead.enqueue("j")
    await store.claim(dead.id, clock())  # claimed, then the process "died"
    fresh = Worker(store, {"j": job}, clock=clock)
    assert await fresh.run_once() == 0  # lease still valid
    clock.now += LEASE + timedelta(seconds=1)
    assert await fresh.run_once() == 1
    await _drain(fresh)
    assert ran == [1] and next(iter(store.rows.values())).status == JobStatus.DONE


async def test_a_busy_worker_does_not_poll_the_database():
    store = MemoryJobStore()
    calls = 0
    real = store.next_wake

    async def counting(worker):
        nonlocal calls
        calls += 1
        return await real(worker)

    store.next_wake = counting  # type: ignore[method-assign]
    release = asyncio.Event()

    async def slow():
        await release.wait()

    w = Worker(store, {"j": slow}, concurrency=1)
    await w.enqueue("j")
    await w.enqueue("j")  # waits for the only slot
    w.start()
    await asyncio.sleep(1.5)
    assert calls == 0  # previously: a query every 0.5 s for as long as the job ran
    release.set()
    await asyncio.sleep(0.2)
    await w.stop()


async def test_an_interrupted_run_does_not_use_up_an_attempt_but_endless_restarts_stop():
    clock = Clock()
    store = MemoryJobStore(clock)

    async def job():
        return None

    w = Worker(store, {"j": job}, clock=clock)
    jid = await w.enqueue("j", max_attempts=1)
    for _ in range(3):  # three deploys in a row, each cutting the run short
        assert (await store.claim("dead", clock())).attempts == 1  # type: ignore[union-attr]
        clock.now += LEASE + timedelta(seconds=1)
    assert await store.claim("w", clock()) is None  # stopped instead of looping forever
    assert store.rows[jid].status == JobStatus.FAILED


async def test_finished_jobs_are_pruned_after_two_weeks():
    from app.queue import KEEP_FINISHED

    clock = Clock()
    store = MemoryJobStore(clock)

    async def job():
        return None

    w = Worker(store, {"j": job}, clock=clock)
    await w.enqueue("j")
    await w.run_once()
    await _drain(w)
    assert await store.prune(clock() - KEEP_FINISHED) == 0
    clock.now += KEEP_FINISHED + timedelta(days=1)
    assert await store.prune(clock() - KEEP_FINISHED) == 1 and store.rows == {}


async def test_marking_done_survives_a_brief_database_blip(monkeypatch):
    import app.queue as q

    monkeypatch.setattr(q.asyncio, "sleep", _no_sleep)
    clock = Clock()
    store = MemoryJobStore(clock)
    real_done, failures = store.done, [1]

    async def flaky_done(*a):
        if failures:
            failures.pop()
            raise ConnectionError("neon waking up")
        await real_done(*a)

    store.done = flaky_done  # type: ignore[method-assign]

    async def job():
        return None

    w = Worker(store, {"j": job}, clock=clock)
    jid = await w.enqueue("j")
    await w.run_once()
    await _drain(w)
    assert store.rows[jid].status == JobStatus.DONE


async def _no_sleep(_seconds):
    return None
