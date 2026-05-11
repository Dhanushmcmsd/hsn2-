"""gst_fetcher.py

Core GST data service with 3-layer fallback:
  Layer 1 → cbic-gst.gov.in scrape
  Layer 2 → services.gst.gov.in HSN lookup API
  Layer 3 → Static CSV at data/hsn_gst_rates.csv
Results are cached in Redis (Upstash) for 23 hours.

Additional public API (CBIC notification sync):
  fetch_latest_gst_notifications() → list[dict]
  fetch_and_sync_gst_rates(db=None) → None
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional, TypedDict

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import async_session
from app.models.gst_rate_history import GSTRateHistory

logger = logging.getLogger(__name__)
log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class GSTRate(TypedDict):
    rate: float
    effective_from: date
    source: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CBIC_RATE_URL = "https://www.cbic.gov.in/htdocs-cbec/gst/notification/notifications.htm"
CBIC_URL = "https://cbic-gst.gov.in/gst-goods-services-rates.html"
GST_SERVICES_URL = "https://services.gst.gov.in/services/searchhsnsac"
REDIS_KEY = "gst:rates:all"
REDIS_TTL = 82800  # 23 hours in seconds
CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "hsn_gst_rates.csv"

_DEFAULT_DATE = date(2017, 7, 1)  # GST rollout date — used when date is absent
_HTTP_TIMEOUT = 20.0
_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DATE_RE = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# Redis helpers (optional — graceful no-op when UPSTASH_REDIS_URL is absent)
# ---------------------------------------------------------------------------

def _get_redis_client():
    """Return an async Redis client or None if not configured."""
    url = os.getenv("UPSTASH_REDIS_URL")
    if not url:
        return None
    try:
        from redis.asyncio import from_url  # type: ignore
        return from_url(url, decode_responses=True)
    except ImportError:
        logger.warning("GST_SYNC: redis package not installed — cache disabled")
        return None


async def _cache_get(key: str) -> dict | None:
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        await client.aclose()
        if raw:
            return json.loads(raw)
    except Exception as exc:
        logger.warning("GST_SYNC: Redis GET failed: %s", exc)
    return None


async def _cache_set(key: str, value: dict, ttl: int) -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
        await client.aclose()
    except Exception as exc:
        logger.warning("GST_SYNC: Redis SET failed: %s", exc)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialise_rates(rates: dict[str, GSTRate]) -> dict:
    """Convert date objects → ISO strings for JSON storage."""
    out = {}
    for hsn, r in rates.items():
        out[hsn] = {
            "rate": r["rate"],
            "effective_from": r["effective_from"].isoformat()
            if isinstance(r["effective_from"], date)
            else r["effective_from"],
            "source": r["source"],
        }
    return out


def _deserialise_rates(raw: dict) -> dict[str, GSTRate]:
    """Reconstruct GSTRate TypedDicts from a cached dict."""
    result: dict[str, GSTRate] = {}
    for hsn, r in raw.items():
        try:
            eff = date.fromisoformat(r["effective_from"])
        except (ValueError, KeyError):
            eff = _DEFAULT_DATE
        result[hsn] = GSTRate(
            rate=float(r.get("rate", 0.0)),
            effective_from=eff,
            source=r.get("source", "cache"),
        )
    return result


# ---------------------------------------------------------------------------
# Layer 1 — CBIC scrape (bulk rate schedule)
# ---------------------------------------------------------------------------

async def _fetch_from_cbic() -> dict[str, GSTRate]:
    """Scrape the CBIC GST rate schedule page."""
    async with httpx.AsyncClient(headers=HEADERS, timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(CBIC_URL)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    rates: dict[str, GSTRate] = {}

    for table in soup.find_all("table"):
        headers_row = table.find("tr")
        if not headers_row:
            continue
        col_texts = [th.get_text(strip=True).lower() for th in headers_row.find_all(["th", "td"])]

        hsn_col = next((i for i, h in enumerate(col_texts) if "hsn" in h), None)
        rate_col = next(
            (i for i, h in enumerate(col_texts) if "rate" in h or "gst" in h or "%" in h), None
        )
        date_col = next(
            (i for i, h in enumerate(col_texts) if "date" in h or "effective" in h or "w.e.f" in h),
            None,
        )

        if hsn_col is None or rate_col is None:
            continue

        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(filter(None, [hsn_col, rate_col, date_col or 0])):
                continue

            hsn_raw = cells[hsn_col].get_text(strip=True).replace(" ", "").replace("-", "")
            rate_raw = cells[rate_col].get_text(strip=True).replace("%", "").strip()

            if not hsn_raw or not rate_raw:
                continue

            try:
                rate_val = float(rate_raw)
            except ValueError:
                continue

            eff_date = _DEFAULT_DATE
            if date_col is not None and len(cells) > date_col:
                date_str = cells[date_col].get_text(strip=True)
                for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
                    try:
                        eff_date = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue

            rates[hsn_raw] = GSTRate(rate=rate_val, effective_from=eff_date, source="cbic")

    if not rates:
        raise ValueError("CBIC scrape returned no parseable rows")

    logger.info("GST_SYNC: Layer 1 (CBIC) fetched %d entries", len(rates))
    return rates


# ---------------------------------------------------------------------------
# Layer 2 — services.gst.gov.in per-HSN lookup
# ---------------------------------------------------------------------------

async def _fetch_from_gst_services(hsn_codes: list[str]) -> dict[str, GSTRate]:
    """
    Fetch GST rates for a list of HSN codes from services.gst.gov.in.
    Rate-limited to 1 req/sec; capped at 100 codes per run.
    """
    rates: dict[str, GSTRate] = {}
    codes_to_fetch = hsn_codes[:100]

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0) as client:
        for hsn in codes_to_fetch:
            try:
                payload = {"hsnSacCode": hsn, "hsnSacType": "HSN"}
                resp = await client.post(GST_SERVICES_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

                rate_val: float | None = None
                for key in ("taxRate", "gstRate", "rate", "igst"):
                    if key in data:
                        try:
                            rate_val = float(str(data[key]).replace("%", ""))
                            break
                        except (ValueError, TypeError):
                            pass

                if rate_val is None and isinstance(data.get("data"), list) and data["data"]:
                    row = data["data"][0]
                    for key in ("taxRate", "gstRate", "rate", "igst"):
                        if key in row:
                            try:
                                rate_val = float(str(row[key]).replace("%", ""))
                                break
                            except (ValueError, TypeError):
                                pass

                if rate_val is not None:
                    rates[hsn] = GSTRate(
                        rate=rate_val,
                        effective_from=_DEFAULT_DATE,
                        source="gst-services",
                    )
            except Exception as exc:
                logger.debug("GST_SYNC: Layer 2 failed for HSN %s: %s", hsn, exc)

            await asyncio.sleep(1)

    if not rates:
        raise ValueError("GST services lookup returned no data")

    logger.info("GST_SYNC: Layer 2 (gst.gov.in) fetched %d entries", len(rates))
    return rates


# ---------------------------------------------------------------------------
# Layer 3 — Static CSV fallback
# ---------------------------------------------------------------------------

def _load_from_csv() -> dict[str, GSTRate]:
    """
    Load GST rates from data/hsn_gst_rates.csv.
    Expected columns: hsn_code, gst_rate, effective_from, notes
    Always succeeds (returns empty dict if file missing).
    """
    logger.warning("GST_SYNC: Using stale CSV fallback — manual update needed")

    rates: dict[str, GSTRate] = {}
    if not CSV_PATH.exists():
        logger.error("GST_SYNC: CSV fallback not found at %s", CSV_PATH)
        return rates

    with CSV_PATH.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            hsn = row.get("hsn_code", "").strip()
            if not hsn:
                continue
            try:
                rate_val = float(row.get("gst_rate", "0").strip())
            except ValueError:
                rate_val = 0.0

            eff_date = _DEFAULT_DATE
            raw_date = row.get("effective_from", "").strip()
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
                try:
                    eff_date = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    continue

            rates[hsn] = GSTRate(rate=rate_val, effective_from=eff_date, source="csv-fallback")

    logger.info("GST_SYNC: CSV fallback loaded %d entries", len(rates))
    return rates


# ---------------------------------------------------------------------------
# Bulk public API (existing)
# ---------------------------------------------------------------------------

async def fetch_all_gst_rates() -> dict[str, GSTRate]:
    """
    Fetch all GST rates using the 3-layer fallback chain.
    Results are cached in Redis for 23 hours.
    Returns dict[hsn_code, GSTRate].
    """
    cached = await _cache_get(REDIS_KEY)
    if cached:
        logger.info("GST_SYNC: Returning cached GST rates (%d entries)", len(cached))
        return _deserialise_rates(cached)

    rates: dict[str, GSTRate] = {}

    try:
        rates = await _fetch_from_cbic()
    except Exception as exc:
        logger.warning("GST_SYNC: Layer 1 (CBIC) failed: %s — trying Layer 2", exc)
        try:
            raise ValueError("Layer 2 bulk fetch skipped; use fetch_gst_rate_for_hsn for targeted lookup")
        except Exception as exc2:
            logger.warning("GST_SYNC: Layer 2 skipped: %s — using CSV fallback", exc2)
            rates = _load_from_csv()

    if rates:
        await _cache_set(REDIS_KEY, _serialise_rates(rates), REDIS_TTL)

    return rates


async def fetch_gst_rate_for_hsn(hsn_code: str) -> GSTRate | None:
    """
    Fetch the GST rate for a single HSN code.
    Checks cached bulk data first; falls back through all 3 layers for the
    specific code if not found.
    """
    hsn_code = hsn_code.strip().replace(" ", "").replace("-", "")

    all_rates = await fetch_all_gst_rates()
    if hsn_code in all_rates:
        return all_rates[hsn_code]

    for key, val in all_rates.items():
        if key.startswith(hsn_code) or hsn_code.startswith(key):
            return val

    try:
        result = await _fetch_from_gst_services([hsn_code])
        if hsn_code in result:
            return result[hsn_code]
    except Exception as exc:
        logger.warning("GST_SYNC: Targeted Layer 2 failed for %s: %s", hsn_code, exc)

    csv_rates = _load_from_csv()
    return csv_rates.get(hsn_code)


# ---------------------------------------------------------------------------
# CBIC notification scraping + GSTRateHistory sync (new)
# ---------------------------------------------------------------------------

async def fetch_latest_gst_notifications() -> list[dict]:
    """
    GET the CBIC notifications page and parse the HTML table.

    Filters rows whose second <td> cell contains the word "Rate" (case-insensitive).

    Returns
    -------
    list of dicts with keys:
        title (str)  — notification title / description
        date  (str)  — raw date string as it appears in the table
        url   (str)  — absolute URL to the notification document (or CBIC_RATE_URL
                        as fallback when no link is present)
    """
    notifications: list[dict] = []

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        headers=HEADERS,
        follow_redirects=True,
    ) as client:
        response = await client.get(CBIC_RATE_URL)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            second_cell_text = cells[1].get_text(separator=" ", strip=True)
            if "rate" not in second_cell_text.lower():
                continue

            title = second_cell_text
            date_raw = cells[0].get_text(strip=True)

            anchor = row.find("a", href=True)
            if anchor:
                href = anchor["href"].strip()
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = "https://www.cbic.gov.in" + href
                else:
                    url = "https://www.cbic.gov.in/" + href.lstrip("./")
            else:
                url = CBIC_RATE_URL

            notifications.append({"title": title, "date": date_raw, "url": url})

    log.info(
        "gst_fetcher.notifications_scraped",
        total=len(notifications),
        url=CBIC_RATE_URL,
    )
    return notifications


def _parse_date(raw: str) -> Optional[date]:
    """Try to extract a date from a raw string. Returns None on failure."""
    m = _DATE_RE.search(raw)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_rate(title: str) -> Optional[float]:
    """Extract the first percentage value from a notification title."""
    m = _RATE_RE.search(title)
    return float(m.group(1)) if m else None


async def fetch_and_sync_gst_rates(
    db: Optional[AsyncSession] = None,
) -> None:
    """
    Fetch CBIC notifications and upsert into the ``gst_rate_history`` table.

    Parameters
    ----------
    db : AsyncSession, optional
        An already-open SQLAlchemy async session. When None (the default),
        this function opens its own session via the ``async_session`` factory
        from ``app.models.database``.

    The function is fully exception-safe: all errors are logged and swallowed
    so that a nightly scheduler task is never crashed by a transient network
    or parse failure.
    """
    # ── 1. Scrape ────────────────────────────────────────────────────────────
    try:
        notifications = await fetch_latest_gst_notifications()
    except Exception as exc:
        log.error(
            "gst_fetcher.scrape_failed",
            error=str(exc),
            url=CBIC_RATE_URL,
        )
        return

    if not notifications:
        log.info("gst_fetcher.no_notifications_found")
        return

    # ── 2. Persist ───────────────────────────────────────────────────────────
    _own_session = db is None
    session: AsyncSession = db if db is not None else async_session()

    try:
        inserted = 0
        skipped = 0

        for notif in notifications:
            title: str = notif["title"]
            date_raw: str = notif["date"]
            source_url: str = notif["url"]

            effective_from = _parse_date(date_raw)
            gst_rate = _parse_rate(title)

            if effective_from is None or gst_rate is None:
                log.info(
                    "gst_fetcher.row_skipped",
                    reason="could not parse date or rate",
                    title=title,
                    date_raw=date_raw,
                )
                skipped += 1
                continue

            try:
                existing = (
                    await session.execute(
                        select(GSTRateHistory).where(
                            GSTRateHistory.source_url == source_url,
                            GSTRateHistory.effective_from == effective_from,
                        )
                    )
                ).scalars().first()

                if existing is not None:
                    existing.gst_rate = gst_rate
                    existing.fetched_at = datetime.utcnow()
                else:
                    session.add(
                        GSTRateHistory(
                            hsn_code="00000000",  # CBIC page-level notifications have no single HSN
                            gst_rate=gst_rate,
                            effective_from=effective_from,
                            effective_to=None,
                            source_url=source_url,
                        )
                    )
                    inserted += 1

            except Exception as row_exc:
                log.error(
                    "gst_fetcher.row_upsert_failed",
                    error=str(row_exc),
                    title=title,
                    source_url=source_url,
                )
                skipped += 1
                continue

        await session.commit()
        log.info(
            "gst_fetcher.sync_complete",
            inserted=inserted,
            skipped=skipped,
            total=len(notifications),
        )

    except Exception as exc:
        log.error("gst_fetcher.sync_failed", error=str(exc))
        try:
            await session.rollback()
        except Exception:
            pass

    finally:
        if _own_session:
            await session.close()
