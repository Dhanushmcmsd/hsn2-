"""
app/services/gst_fetcher.py
Core GST data service with 3-layer fallback:
  Layer 1 → cbic-gst.gov.in scrape
  Layer 2 → services.gst.gov.in HSN lookup API
  Layer 3 → Static CSV at data/hsn_gst_rates.csv
Results are cached in Redis (Upstash) for 23 hours.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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

CBIC_URL = "https://cbic-gst.gov.in/gst-goods-services-rates.html"
GST_SERVICES_URL = "https://services.gst.gov.in/services/searchhsnsac"
REDIS_KEY = "gst:rates:all"
REDIS_TTL = 82800  # 23 hours in seconds
CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "hsn_gst_rates.csv"

_DEFAULT_DATE = date(2017, 7, 1)  # GST rollout date — used when date is absent

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
# Layer 1 — CBIC scrape
# ---------------------------------------------------------------------------

async def _fetch_from_cbic() -> dict[str, GSTRate]:
    """Scrape the CBIC GST rate schedule page."""
    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(CBIC_URL)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    rates: dict[str, GSTRate] = {}

    for table in soup.find_all("table"):
        headers_row = table.find("tr")
        if not headers_row:
            continue
        col_texts = [th.get_text(strip=True).lower() for th in headers_row.find_all(["th", "td"])]

        # Identify columns by keyword presence
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

                # Response schema varies; attempt common paths
                rate_val: float | None = None
                for key in ("taxRate", "gstRate", "rate", "igst"):
                    if key in data:
                        try:
                            rate_val = float(str(data[key]).replace("%", ""))
                            break
                        except (ValueError, TypeError):
                            pass

                # Try nested under a list
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

            await asyncio.sleep(1)  # 1 req/sec rate limit

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
# Public API
# ---------------------------------------------------------------------------

async def fetch_all_gst_rates() -> dict[str, GSTRate]:
    """
    Fetch all GST rates using the 3-layer fallback chain.
    Results are cached in Redis for 23 hours.
    Returns dict[hsn_code, GSTRate].
    """
    # --- Check Redis cache first ---
    cached = await _cache_get(REDIS_KEY)
    if cached:
        logger.info("GST_SYNC: Returning cached GST rates (%d entries)", len(cached))
        return _deserialise_rates(cached)

    rates: dict[str, GSTRate] = {}

    # Layer 1 — CBIC scrape
    try:
        rates = await _fetch_from_cbic()
    except Exception as exc:
        logger.warning("GST_SYNC: Layer 1 (CBIC) failed: %s — trying Layer 2", exc)

        # Layer 2 — GST Services (needs a seed list; use empty to trigger fallback)
        try:
            # We don't have a full HSN list here; Layer 2 is more useful when
            # called from fetch_gst_rate_for_hsn with a specific code.
            # For bulk fetch, raise immediately to fall through to CSV.
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

    # Check bulk cache first
    all_rates = await fetch_all_gst_rates()
    if hsn_code in all_rates:
        return all_rates[hsn_code]

    # Also check prefix matches (e.g. 4-digit code matching 8-digit entries)
    for key, val in all_rates.items():
        if key.startswith(hsn_code) or hsn_code.startswith(key):
            return val

    # Targeted Layer 2 lookup for unknown HSN
    try:
        result = await _fetch_from_gst_services([hsn_code])
        if hsn_code in result:
            return result[hsn_code]
    except Exception as exc:
        logger.warning("GST_SYNC: Targeted Layer 2 failed for %s: %s", hsn_code, exc)

    # Last resort: CSV
    csv_rates = _load_from_csv()
    return csv_rates.get(hsn_code)
