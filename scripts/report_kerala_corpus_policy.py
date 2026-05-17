#!/usr/bin/env python3
"""Report Kerala corpus policy diagnostics: curated/corpus conflicts, duplicate ambiguity."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "data" / "kerala_retail_aliases.json"


def main() -> int:
    from app.services.kerala_aliases import CURATED_KERALA_ALIAS_MAP
    from app.services.kerala_corpus_hints import _load_corpus_raw
    from app.services.kerala_corpus_maps import corpus_derived_alias_map
    from app.services.kerala_search_policy import (
        analyze_duplicate_corpus_terms,
        curated_overrides_corpus,
        hint_only_standalone_tokens,
    )

    derived = corpus_derived_alias_map()
    conflicts = curated_overrides_corpus(CURATED_KERALA_ALIAS_MAP, derived)
    dup_report = analyze_duplicate_corpus_terms(_load_corpus_raw())

    print("=== Kerala search policy report ===\n")
    print(f"Hint-only standalone tokens ({len(hint_only_standalone_tokens())}):")
    print(" ", ", ".join(sorted(hint_only_standalone_tokens())[:20]), "...")

    print(f"\nCurated vs corpus HSN conflicts ({len(conflicts)}):")
    for row in conflicts[:25]:
        print(
            f"  {row['key']}: corpus={row['corpus_hsn']} curated={row['curated_hsn']} "
            f"({row['policy']})"
        )
    if len(conflicts) > 25:
        print(f"  ... and {len(conflicts) - 25} more")

    print(f"\nDuplicate token groups: {dup_report['duplicate_token_groups']}")
    amb = dup_report["strictly_ambiguous_terms"]
    print(f"Strictly ambiguous (conservative standalone block): {len(amb)}")
    for term in amb[:15]:
        print(f"  - {term}")
    mixed = dup_report["mixed_priority_duplicates"]
    if mixed:
        print(f"\nMixed-priority duplicates ({len(mixed)}):")
        for row in mixed[:10]:
            print(f"  {row['term']}: priorities={row['priorities']} policy={row['policy']}")

    out_path = ROOT / "data" / "kerala_policy_report.json"
    payload = {
        "conflicts": conflicts,
        "duplicate_analysis": dup_report,
        "hint_only_standalone_count": len(hint_only_standalone_tokens()),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
