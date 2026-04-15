"""
Vinted.pl hunter — pobiera nowe oferty dla zadanych fraz,
zapisuje surowy JSON do data/latest.json i data/history/<date>.json.

Nie wysyła maila, nie filtruje subiektywnie, nie ocenia perełek —
to robi Claude w rozmowie na podstawie JSON-a.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from vinted_api_wrapper import Vinted

# ── Konfiguracja ─────────────────────────────────────────────────────────────

QUERIES: list[str] = [
    "zabawki drewniane",
    "drewniane puzzle",
    "sorter drewniany",
    "klocki drewniane",
]

LOOKBACK_HOURS = 48          # zapas — Claude odfiltruje dokładnie na 12h
PER_PAGE = 96
MAX_PAGES = 3
DOMAIN = "pl"
SLEEP_BETWEEN_PAGES = 1.0
SLEEP_BETWEEN_QUERIES = 2.0

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LATEST = DATA / "latest.json"
HISTORY = DATA / "history"


@dataclass
class Offer:
    id: int
    query: str
    title: str
    price_amount: float
    price_currency: str
    brand: str | None
    status: str | None
    size: str | None
    url: str
    photo_url: str | None
    seller_login: str | None
    seller_feedback_count: int | None
    seller_country: str | None
    created_at: str
    fetched_at: str
    raw_description_excerpt: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _safe(obj, *path, default=None):
    cur = obj
    for p in path:
        if cur is None:
            return default
        cur = getattr(cur, p, None) if not isinstance(cur, dict) else cur.get(p)
    return cur if cur is not None else default


def to_offer(item, query: str, now_iso: str) -> Offer | None:
    try:
        created_ts = getattr(item, "created_at_ts", None) or getattr(item, "created_at", None)
        if isinstance(created_ts, (int, float)):
            created_iso = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()
        else:
            created_iso = str(created_ts) if created_ts else now_iso

        price = getattr(item, "price", None)
        amount = float(_safe(price, "amount", default=0) or 0)
        currency = _safe(price, "currency_code", default="PLN") or "PLN"

        user = getattr(item, "user", None)
        desc = getattr(item, "description", "") or ""
        desc_excerpt = (desc[:500] + "…") if len(desc) > 500 else desc

        return Offer(
            id=int(item.id),
            query=query,
            title=getattr(item, "title", "") or "",
            price_amount=amount,
            price_currency=currency,
            brand=getattr(item, "brand_title", None),
            status=getattr(item, "status", None),
            size=getattr(item, "size_title", None),
            url=getattr(item, "url", "") or "",
            photo_url=_safe(getattr(item, "photo", None), "url"),
            seller_login=_safe(user, "login"),
            seller_feedback_count=_safe(user, "feedback_count"),
            seller_country=_safe(user, "country_title_local"),
            created_at=created_iso,
            fetched_at=now_iso,
            raw_description_excerpt=desc_excerpt,
        )
    except Exception as e:
        print(f"  [skip] {getattr(item, 'id', '?')}: {e}")
        return None


def scrape() -> list[Offer]:
    vinted = Vinted(domain=DOMAIN)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    by_id: dict[int, Offer] = {}

    for q in QUERIES:
        print(f"\n→ '{q}'")
        for page in range(1, MAX_PAGES + 1):
            try:
                items = vinted.search(query=q, page=page, per_page=PER_PAGE, order="newest_first")
            except Exception as e:
                print(f"  [error page {page}] {e}")
                break
            if not items:
                break

            added = 0
            stop = False
            for it in items:
                off = to_offer(it, q, now_iso)
                if off is None:
                    continue
                try:
                    created = datetime.fromisoformat(off.created_at.replace("Z", "+00:00"))
                except Exception:
                    created = now
                if created < cutoff:
                    stop = True
                    continue
                if off.id not in by_id:
                    by_id[off.id] = off
                    added += 1
                else:
                    by_id[off.id].extra.setdefault("also_matched_queries", []).append(q)

            print(f"  page {page}: +{added} (łącznie {len(by_id)})")
            time.sleep(SLEEP_BETWEEN_PAGES)
            if stop or len(items) < PER_PAGE:
                break
        time.sleep(SLEEP_BETWEEN_QUERIES)

    return sorted(by_id.values(), key=lambda o: o.created_at, reverse=True)


def save(offers: list[Offer]) -> None:
    DATA.mkdir(exist_ok=True)
    HISTORY.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(),
        "lookback_hours": LOOKBACK_HOURS,
        "queries": QUERIES,
        "count": len(offers),
        "offers": [asdict(o) for o in offers],
    }
    LATEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    stamp = now.strftime("%Y-%m-%dT%H-%M")
    (HISTORY / f"{stamp}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n✔ zapisano {len(offers)} ofert → {LATEST.relative_to(ROOT)}")


if __name__ == "__main__":
    save(scrape())
