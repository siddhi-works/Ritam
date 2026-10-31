"""Re-verify every catalogue URL live:  python -m app.discovery.check"""

import asyncio

import httpx

from app.discovery import catalogue
from app.ingest.fetch import USER_AGENT


async def main() -> int:
    bad = 0
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=40, follow_redirects=True
    ) as client:
        for card in catalogue():
            for s in card.sources:
                try:
                    r = await client.get(s["url"], headers={"Range": "bytes=0-2047"})
                    status = r.status_code
                except httpx.HTTPError as exc:
                    status = type(exc).__name__  # type: ignore[assignment]
                # Pages marked render:true block plain HTTP but are fetched through Jina Reader.
                ok = status in (200, 206) or (bool(s.get("render")) and status == 403)
                bad += 0 if ok else 1
                print(f"{'OK ' if ok else 'BAD'} {status} {card.id:22} {s['kind']:13} {s['url']}")
    print(f"{bad} problem(s)")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if asyncio.run(main()) else 0)
