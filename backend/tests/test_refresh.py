from types import SimpleNamespace

from app.refresh import QUESTION, queue_card_reports


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, x):
        self.added.append(x)

    def add_all(self, xs):
        self.added.extend(xs)

    async def flush(self):
        return None

    async def commit(self):
        return None


async def test_every_catalogue_card_gets_a_queued_report_from_official_sources(monkeypatch):
    import app.refresh as r

    async def ok(url):
        return url

    monkeypatch.setattr(r, "check_url", ok)
    s = FakeSession()
    created = await queue_card_reports(s, only_missing=False)  # type: ignore[arg-type]
    audits = [x for x in s.added if type(x).__name__ == "Audit"]
    assert len(created) == len(audits) >= 15
    assert all(a.question == QUESTION and a.status.value == "queued" for a in audits)


async def test_only_missing_skips_cards_with_a_report(monkeypatch):
    import app.refresh as r

    async def ok(url):
        return url

    async def have(session, names):
        return {n: SimpleNamespace() for n in names[:3]}

    monkeypatch.setattr(r, "check_url", ok)
    monkeypatch.setattr(r, "latest_public_reports", have)
    created = await queue_card_reports(FakeSession(), only_missing=True)  # type: ignore[arg-type]
    assert len(created) == 12
