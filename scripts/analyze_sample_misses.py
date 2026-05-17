#!/usr/bin/env python3
"""Analyze sample.xlsx classification: detection gaps and suspicious HSN."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _load_env() -> None:
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _why(out: dict) -> str:
    from scripts.test_client_excel import _is_detected

    if _is_detected(out):
        return "ok"
    hsn = (out.get("hsn_code") or "").strip()
    if not hsn or hsn in ("UNKNOWN", "UNCLASSIFIED", "99999999"):
        return "no_hsn"
    if out.get("gst_rate") is None:
        return "gst_null"
    if int(out.get("confidence") or 0) < 70:
        return "low_conf"
    if out.get("needs_manual_review") or out.get("review_required"):
        if out.get("rate_conflict"):
            return "rate_conflict_review"
        return "review_flag"
    return "other"


async def main() -> None:
    _load_env()
    os.environ.setdefault("SECRET_KEY", "excel-test-secret-key-32chars-min")
    os.environ.setdefault("API_KEY", "dev-api-key")
    os.environ.setdefault("ADMIN_API_KEY", "dev-admin-key")
    os.environ["FAISS_DISABLED"] = "1"

    from scripts.test_client_excel import _load_names, _is_detected

    excel = Path(r"c:\Users\Admin\Pictures\sample.xlsx")
    names = _load_names(excel)[:500]

    from app.models.database import async_session, init_db
    from app.services.gst_classifier import classify

    await init_db()
    reasons: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    rows: list[dict] = []

    for desc in names:
        async with async_session() as db:
            out = await classify(db, desc, bypass_cache=True)
        reason = _why(out)
        reasons[reason] += 1
        layer = out.get("matched_layer") or "?"
        layers[layer] += 1
        rows.append({
            "description": desc,
            "reason": reason,
            "detected": _is_detected(out),
            "hsn_code": out.get("hsn_code"),
            "gst_rate": out.get("gst_rate"),
            "confidence": out.get("confidence"),
            "review_required": out.get("review_required"),
            "rate_conflict": out.get("rate_conflict"),
            "trust_level": out.get("trust_level"),
            "matched_layer": layer,
            "tier_used": out.get("tier_used"),
        })

    print(json.dumps({"total": len(names), "reasons": dict(reasons), "layers": dict(layers)}, indent=2))
    missed = [r for r in rows if not r["detected"]]
    print(f"\nUndetected: {len(missed)}/{len(names)}")
    for r in missed[:25]:
        print(
            f"  {r['description'][:48]:48} | {r['reason']:22} | "
            f"{r['hsn_code']} gst={r['gst_rate']} rv={r['review_required']} "
            f"rc={r['rate_conflict']} trust={r['trust_level']}"
        )

    out_path = ROOT / "scripts" / "sample_miss_analysis.json"
    out_path.write_text(json.dumps({"reasons": dict(reasons), "rows": rows}, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
