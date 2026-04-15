from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pyVinted import Vinted


QUERIES: list[str] = [
    "zabawki drewniane",
    "drewniane puzzle",
    "sorter drewniany",
    "klocki drewniane",
]

LOOKBACK_HOURS = 48
PER_PAGE = 96
MAX_PAGES = 3
BASE_URL = "https://www.vinted.pl/catalog"
COUNTRY_ID_PL = 180
PRICE_TO_PLN = 80
HISTORY_KEEP_HOURS = 72
SLEEP_BETWEEN_PAGES = 1.5
SLEEP_BETWEEN_QUERIES = 2.5

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


def build_search_url(query: str) -> str:
    params = [
        ("search_text", query),
        ("order", "newest_first"),
        ("currency", "PLN"),
        ("country_ids[]", str(COUNTRY_ID_PL)),
        ("price_to", str(PRICE_TO_PLN)),
    ]
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"


FOREIGN_CHARS = set(
    "áéíúýàèìòùâêîôûãõäöüÿåæøßřěůőűšžčťďňľĺŕșțăîģķļņūīėįųõõ"
    "ÁÉÍÚÝÄÖÜÅÆØŘĚŮŐŰŠŽČŤĎŇĽĹŔ"
)

FOREIGN_WORDS = (
    "drevene", "drevena", "dreveny", "hracka", "hracky", "kostky", "kocky",
    "detske", "vkladacka", "skluzavka", "kulickov", "domcek",
    "jatek", "keszlet", "mese ", "vandor", " kis ",
    "puinen", "puiset", "palapel", "laatikko", "leikkiauto", "elaim", "nuppi",
    "manguasi", "iminap",
    " koka ", "koka.", " koks", " puzle",
    "medine", "medines", "medzio",
    " lemn", "jucari", "masin", "foto lemn",
    "holz", "spielzeug",
    "bondegard", "dukkeh", " pussel", " bitars", "sodt ",
)


def is_likely_polish(title: str) -> bool:
    if not title:
        return True
    if any(c in FOREIGN_CHARS for c in title):
        return False
    low = title.lower()
    if any(w in low for w in FOREIGN_WORDS):
        return False
    return True


def _dget(d: dict | None, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur if cur is not None else default


def to_offer(item, query: str, now_iso: str) -> Offer | None:
    try:
        raw = getattr(item, "raw_data", None) or {}

        created_ts = getattr(item, "raw_timestamp", None)
        if isinstance(created_ts, (int, float)):
            created_iso = datetime.fromtimestamp(int(created_ts), tz=timezone.utc).isoformat()
        else:
            created_dt = getattr(item, "created_at_ts", None)
            if isinstance(created_dt, datetime):
                created_iso = created_dt.astimezone(timezone.utc).isoformat()
            else:
                created_iso = now_iso

        price_raw = getattr(item, "price", None)
        try:
            amount = float(price_raw) if price_raw is not None else 0.0
        except (TypeError, ValueError):
            amount = float(_dget(raw, "price", "amount", default=0) or 0)
        currency = (
            getattr(item, "currency", None)
            or _dget(raw, "price", "currency_code")
            or "PLN"
        )

        user = _dget(raw, "user") or {}
        desc = _dget(raw, "description", default="") or ""
        desc_excerpt = (desc[:500] + "…") if len(desc) > 500 else desc

        return Offer(
            id=int(getattr(item, "id", 0) or _dget(raw, "id", default=0)),
            query=query,
            title=getattr(item, "title", "") or _dget(raw, "title", default="") or "",
            price_amount=amount,
            price_currency=str(currency),
            brand=getattr(item, "brand_title", None) or _dget(raw, "brand_title"),
            status=_dget(raw, "status"),
            size=getattr(item, "size_title", None) or _dget(raw, "size_title"),
            url=getattr(item, "url", "") or _dget(raw, "url", default="") or "",
            photo_url=getattr(item, "photo", None) or _dget(raw, "photo", "url"),
            seller_login=_dget(user, "login"),
            seller_feedback_count=_dget(user, "feedback_count"),
            seller_country=_dget(user, "country_title_local") or _dget(user, "country_title"),
            created_at=created_iso,
            fetched_at=now_iso,
            raw_description_excerpt=desc_excerpt,
        )
    except Exception as e:
        print(f"  [skip] {getattr(item, 'id', '?')}: {e}")
        return None


def scrape() -> list[Offer]:
    vinted = Vinted()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    by_id: dict[int, Offer] = {}

    for q in QUERIES:
        url = build_search_url(q)
        print(f"\n→ '{q}'  ({url})")
        for page in range(1, MAX_PAGES + 1):
            try:
                items = vinted.items.search(url, PER_PAGE, page)
            except Exception as e:
                print(f"  [error page {page}] {e}")
                break
            if not items:
                break

            added = 0
            skipped_foreign = 0
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
                if not is_likely_polish(off.title):
                    skipped_foreign += 1
                    continue
                if off.id not in by_id:
                    by_id[off.id] = off
                    added += 1
                else:
                    by_id[off.id].extra.setdefault("also_matched_queries", []).append(q)

            print(f"  page {page}: +{added}, skip_foreign={skipped_foreign} (łącznie {len(by_id)})")
            time.sleep(SLEEP_BETWEEN_PAGES)
            if stop or len(items) < PER_PAGE:
                break
        time.sleep(SLEEP_BETWEEN_QUERIES)

    return sorted(by_id.values(), key=lambda o: o.created_at, reverse=True)


def prune_history(now: datetime) -> int:
    if not HISTORY.exists():
        return 0
    cutoff = now - timedelta(hours=HISTORY_KEEP_HOURS)
    removed = 0
    for f in HISTORY.glob("*.json"):
        try:
            stem = f.stem
            dt = datetime.strptime(stem, "%Y-%m-%dT%H-%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt < cutoff:
            f.unlink()
            removed += 1
    return removed


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
    removed = prune_history(now)
    if removed:
        print(f"  prune: {removed}")
    print(f"\n✔ {len(offers)} → {LATEST.relative_to(ROOT)}")


if __name__ == "__main__":
    save(scrape())
