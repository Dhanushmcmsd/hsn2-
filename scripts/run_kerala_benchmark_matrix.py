#!/usr/bin/env python3
"""Run Kerala invoice benchmark matrix: before/after seed × FAISS on/off."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
EXCEL = ROOT / "data" / "kerala_invoice_benchmark.xlsx"
OUT_DIR = ROOT / "scripts" / "kerala_benchmark_matrix"


def _load_env() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def _set_kerala_corpus_active(active: bool) -> int:
    from sqlalchemy import text

    from app.models.database import async_session, init_db

    await init_db()
    async with async_session() as db:
        r = await db.execute(
            text(
                """
                UPDATE language_aliases
                SET is_active = :active
                WHERE source = 'KERALA_RETAIL_CORPUS'
                """
            ),
            {"active": active},
        )
        await db.commit()
        n = (
            await db.execute(
                text(
                    """
                    SELECT COUNT(*) FROM language_aliases
                    WHERE source = 'KERALA_RETAIL_CORPUS' AND is_active = TRUE
                    """
                )
            )
        ).scalar()
    return int(n or 0)


def _run_benchmark(
    *,
    label: str,
    skip_faiss: bool,
    require_corpus: bool,
) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{label}.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "test_client_excel.py"),
        "--neon",
        "--excel",
        str(EXCEL),
        "--full",
        "--output",
        str(out),
    ]
    if require_corpus:
        cmd.append("--require-kerala-corpus")
    if skip_faiss:
        cmd.append("--skip-faiss")
    else:
        os.environ.pop("FAISS_DISABLED", None)

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if skip_faiss:
        env["FAISS_DISABLED"] = "1"

    print(f"\n>>> {label} (skip_faiss={skip_faiss}, require_corpus={require_corpus})")
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stdout[-4000:] if proc.stdout else "")
        print(proc.stderr[-4000:] if proc.stderr else "", file=sys.stderr)
        raise SystemExit(f"Benchmark failed: {label} exit={proc.returncode}")
    tail = (proc.stdout or "").splitlines()[-15:]
    for line in tail:
        print(line)
    return json.loads(out.read_text(encoding="utf-8"))


def _summarize(report: dict) -> dict:
    return {
        "total": report.get("total_products"),
        "detection_pct": report.get("detection_score_pct"),
        "detected": report.get("detected"),
        "kerala_style_total": report.get("kerala_style_total"),
        "kerala_detected": report.get("kerala_detected"),
        "kerala_hit_rate_pct": report.get("kerala_hit_rate_pct"),
        "kerala_exact_or_alias_hits": report.get("kerala_exact_or_alias_hits"),
        "kerala_corpus_db": (report.get("benchmark_metadata") or {}).get("kerala_corpus_count"),
        "seeded": (report.get("benchmark_metadata") or {}).get("kerala_corpus_seeded"),
    }


async def main_async() -> int:
    _load_env()
    if not EXCEL.exists():
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build_kerala_invoice_benchmark_xlsx.py")])

    # Ensure corpus fresh + seeded
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build_kerala_retail_corpus.py")])
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "seed_kerala_language_aliases.py")])

    active_n = await _set_kerala_corpus_active(True)
    print(f"Kerala corpus active rows: {active_n}")

    matrix: dict = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "excel": str(EXCEL),
        "runs": {},
    }

    # After seed — no FAISS
    matrix["runs"]["after_seed_no_faiss"] = _summarize(
        _run_benchmark(label="after_seed_no_faiss", skip_faiss=True, require_corpus=True)
    )

    # After seed — FAISS on
    try:
        matrix["runs"]["after_seed_faiss"] = _summarize(
            _run_benchmark(label="after_seed_faiss", skip_faiss=False, require_corpus=True)
        )
    except SystemExit as exc:
        matrix["runs"]["after_seed_faiss"] = {"error": str(exc)}

    # Before seed (DB corpus deactivated) — no FAISS
    deactivated = await _set_kerala_corpus_active(False)
    print(f"Deactivated Kerala corpus (active now {deactivated})")
    matrix["runs"]["before_seed_no_faiss"] = _summarize(
        _run_benchmark(label="before_seed_no_faiss", skip_faiss=True, require_corpus=False)
    )

    # Before seed — FAISS on
    try:
        matrix["runs"]["before_seed_faiss"] = _summarize(
            _run_benchmark(label="before_seed_faiss", skip_faiss=False, require_corpus=False)
        )
    except SystemExit as exc:
        matrix["runs"]["before_seed_faiss"] = {"error": str(exc)}

    # Restore seed
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "seed_kerala_language_aliases.py")])
    restored = await _set_kerala_corpus_active(True)
    print(f"Restored Kerala corpus active rows: {restored}")

    summary_path = OUT_DIR / "matrix_summary.json"
    summary_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {summary_path}")
    print(json.dumps(matrix["runs"], indent=2))
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
