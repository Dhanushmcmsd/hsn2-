#!/usr/bin/env python3
"""Build data/kerala_retail_aliases.json from curated Kerala retail vocabulary.

This JSON file is the single source of truth for:
  - Neon language_aliases seed (scripts/seed_kerala_language_aliases.py)
  - In-memory transliteration / joined-form maps (app/services/kerala_corpus_maps.py)
  - SQLite local fallback when Postgres aliases are empty

After editing RESEARCH_VOCABULARY:
  python scripts/build_kerala_retail_corpus.py
  python scripts/seed_kerala_language_aliases.py   # Postgres only
  python scripts/verify_neon_seed_counts.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "data" / "kerala_retail_aliases.json"
SOURCE_GROUP = "kerala_retail_corpus"

# (roman, malayalam_script, english, canonical, hsn_or_none, category, ocr_joined, ambiguous)
# hsn_or_none: None for ambiguous standalone tokens
RESEARCH_VOCABULARY: list[tuple] = [
    # Rice / cereals
    ("matta ari", "മട്ട അരി", "matta rice rosematta red rice", "matta rice", "10063090", "rice", None, False),
    ("puzhukkalari", "പുഴുക്കലരി", "parboiled rice kerala", "parboiled rice", "10063090", "rice", None, False),
    ("pacha ari", "പച്ചരി", "raw rice paddy grain", "raw rice", "10061010", "rice", None, False),
    ("nadan ari", "നാടൻ അരി", "traditional local country rice", "country rice", "10063090", "rice", "nadanari", False),
    ("ari", "അരി", "rice grain", "rice", "10063090", "rice", None, False),
    ("idiyappam podi", "ഇടിയപ്പം പൊടി", "idiyappam string hopper rice flour", "idiyappam flour", "11029090", "flours_podi", "idiyappampodi", False),
    ("gothambu podi", "ഗോതമ്പ് പൊടി", "wheat flour atta", "wheat flour", "11010000", "flours_podi", "gothambupodi", False),
    ("aripodi", "അരിപ്പൊടി", "rice flour fine", "rice flour", "11029090", "flours_podi", None, False),
    ("cholam", "ചോളം", "maize corn grain", "maize", "10059000", "cereals", None, False),
    ("mutira", "മുതിര", "horse gram kulthi", "horse gram", "07139090", "pulses", None, False),
    ("kambam", "കമ്പ്", "pearl millet bajra", "pearl millet", "10082930", "cereals", None, False),
    ("moothari", "മൂത്താരി", "finger millet ragi grain", "finger millet", "10082930", "cereals", None, False),
    ("rajma", "രാജമ", "kidney beans rajma", "kidney beans", "07133390", "pulses", None, False),
    ("vellapayar", "വെള്ളപ്പയർ", "black eyed beans cowpea", "black eyed beans", "07133390", "pulses", None, False),
    ("aval", "അവൽ", "beaten rice poha flattened", "poha", "19041020", "cereals", None, False),
    ("rava", "രവ", "semolina rava sooji", "semolina", "11031110", "cereals", None, False),
    ("ney", "നെയ്", "ghee clarified butter", "ghee", "04059020", "dairy", None, False),
    ("neyyu", "നെയ്യ്", "butter ghee dairy", "butter", "04051000", "dairy", None, False),
    # Flours / podi
    ("puttu podi", "പുട്ട് പൊടി", "puttu rice flour steamed", "puttu flour", "11023000", "flours_podi", "puttupodi", False),
    ("appam podi", "അപ്പം പൊടി", "appam idiyappam rice flour batter", "appam flour", "11029090", "flours_podi", "appampodi", False),
    ("ragi podi", "രാഗി പൊടി", "ragi finger millet flour", "ragi flour", "11029090", "flours_podi", "ragipodi", False),
    ("kadala mavu", "കടല മാവ്", "chickpea flour besan gram", "besan flour", "11061090", "flours_podi", "kadalamavu", False),
    ("naalikera mavu", "നാളികേരം മാവ്", "coconut flour", "coconut flour", "11063090", "flours_podi", None, False),
    ("mallipodi", "മല്ലിപൊടി", "coriander powder dhania", "coriander powder", "09092200", "spices_or_powders", "mallipodi", False),
    ("sambar podi", "സാമ്പാർ പൊടി", "sambar masala powder spice", "sambar powder", "09109100", "spices_or_powders", "sambarpodi", False),
    ("rasam podi", "റസം പൊടി", "rasam powder spice", "rasam powder", "09109100", "spices_or_powders", "rasampodi", False),
    ("kaapi podi", "കാപ്പി പൊടി", "coffee powder roasted instant", "coffee powder", "09011100", "spices_or_powders", "kaapipodi", False),
    ("manjal podi", "മഞ്ഞൾപൊടി", "turmeric powder haldi", "turmeric powder", "09103010", "spices_or_powders", "manjalpodi", False),
    ("mulaku podi", "മുളകുപൊടി", "red chilli powder spice", "chilli powder", "09042211", "spices_or_powders", "mulakupodi", False),
    ("chaya podi", "ചായപ്പൊടി", "tea powder black", "tea powder", "09024090", "spices_or_powders", "chayapodi", False),
    ("chaaya podi", "ചായപ്പൊടി", "tea powder black", "tea powder", "09024090", "spices_or_powders", "chaayapodi", False),
    # Pulses / parippu
    ("thuvara parippu", "തുവര പരിപ്പ്", "pigeon pea toor dal split", "toor dal", "07136000", "pulses", "thuvaraparippu", False),
    ("cherupayar", "ചെറുപയർ", "green gram moong dal", "moong dal", "07133190", "pulses", None, False),
    ("uzhunnu", "ഉഴുന്ന്", "urad dal black gram", "urad dal", "07133190", "pulses", None, False),
    ("uzhunu", "ഉഴുന്ന്", "urad dal black gram", "urad dal", "07133190", "pulses", None, False),
    ("kadala", "കടല", "black chana chickpea whole", "chana", "07132090", "pulses", None, False),
    ("vanpayar", "വൻപയർ", "cowpea red lobiya beans", "cowpea", "07133390", "pulses", None, False),
    ("payar", "പയർ", "beans legume green", "beans", "07082000", "produce", None, False),
    ("parippu", "പരിപ്പ്", "dal lentil pulse split", "dal", "07139090", "pulses", None, True),
    # Spices whole / seeds
    ("manjal", "മഞ്ഞൾ", "turmeric haldi fresh root", "turmeric", "09103030", "spices", None, False),
    ("mulaku", "മുളക്", "chilli pepper dry red", "chilli", "09042210", "spices", None, False),
    ("kurumulaku", "കുരുമുളക്", "black pepper whole", "black pepper", "09041130", "spices", None, False),
    ("jeerakam", "ജീരകം", "cumin jeera seeds", "cumin", "09093129", "spices", None, False),
    ("perumjeerakam", "പെരുംജീരകം", "fennel seeds saunf", "fennel", "09096129", "spices", None, False),
    ("kaayam", "കായം", "asafoetida hing powder", "asafoetida", "13019032", "spices", None, False),
    ("uluva", "ഉലുവ", "fenugreek methi seeds", "fenugreek", "09109990", "spices", None, False),
    ("kaduku", "കടുക്", "mustard seeds rai", "mustard seeds", "12075090", "spices", None, False),
    ("ellu", "എള്ള്", "sesame seeds til", "sesame", "12074090", "spices", None, False),
    ("elakka", "ഏലക്ക", "cardamom green elaichi", "cardamom", "09083120", "spices", None, False),
    ("grambu", "ഗ്രാമ്പ്", "cloves whole spice", "cloves", "09071000", "spices", None, False),
    ("karuvapatta", "കറുവപ്പട്ട", "cinnamon stick bark", "cinnamon", "09061100", "spices", None, False),
    ("jathikka", "ജാതിക്ക", "nutmeg seed spice", "nutmeg", "09081100", "spices", None, False),
    ("malli", "മല്ലി", "coriander seeds dhania", "coriander seeds", "09092200", "spices", None, False),
    ("inji", "ഇഞ്ചി", "ginger fresh root", "ginger", "09101190", "spices", None, False),
    ("pacha mulaku", "പച്ചമുളക്", "green chilli fresh", "green chilli", "07096010", "produce", None, False),
    ("unakka mulaku", "ഉണക്ക മുളക്", "dry red chilli whole dried", "dry chilli", "09042210", "spices", "unakkamulaku", False),
    # Oils / sweeteners
    ("velichenna", "വെളിച്ചെണ്ണ", "coconut oil edible", "coconut oil", "15131100", "oils", "vellachenna", False),
    ("thenga", "തേങ്ങ", "coconut fresh kernel", "coconut", "08011200", "produce", None, False),
    ("vellam", "വെള്ളം", "jaggery gur", "jaggery", "17011410", "sweeteners", None, False),
    ("sharkara", "ശർക്കര", "jaggery sugar gur", "jaggery", "17011410", "sweeteners", None, False),
    ("sarkara", "ശർക്കര", "jaggery sugar", "jaggery", "17011410", "sweeteners", None, False),
    ("nallenna", "നല്ലെണ്ണ", "sesame gingelly oil", "sesame oil", "15155090", "oils", None, False),
    ("panjasara", "പഞ്ചസാര", "sugar refined white", "sugar", "17011200", "sweeteners", None, False),
    ("thean", "തേൻ", "honey natural bee", "honey", "04090000", "sweeteners", None, False),
    # Produce / vegetables
    ("vendakka", "വെണ്ടക്ക", "okra ladyfinger vegetable", "okra", "07099990", "produce", None, False),
    ("thakkali", "തക്കാളി", "tomato fresh vegetable", "tomato", "07020000", "produce", None, False),
    ("vellari", "വെള്ളരി", "cucumber fresh vegetable", "cucumber", "07070000", "produce", None, False),
    ("cheriyulli", "ചെറിയുള്ളി", "shallot small onion", "shallot", "07031010", "produce", None, False),
    ("ulli", "ഉള്ളി", "onion shallot", "onion", "07031010", "produce", None, False),
    ("savola", "സവോല", "onion big", "onion", "07031010", "produce", None, False),
    ("veluthulli", "വെളുത്തുള്ളി", "garlic cloves", "garlic", "07032000", "produce", None, False),
    ("muringakkaya", "മുരിങ്ങക്കായ", "drumstick moringa pods", "drumstick", "07099300", "produce", None, False),
    ("nellikka", "നെല്ലിക്ക", "amla gooseberry fruit", "gooseberry", "08109060", "produce", None, False),
    ("chakka", "ചക്ക", "jackfruit fresh tropical", "jackfruit", "08109040", "produce", None, False),
    ("vazhakka", "വാഴക്ക", "plantain banana raw cooking", "plantain", "08030090", "produce", None, False),
    ("nendrakkaya", "നേന്ദ്രക്കായ", "nendran plantain raw", "nendran banana", "08030090", "produce", None, False),
    ("ethakka", "ഏത്തക്ക", "ethakka plantain banana", "plantain", "08030090", "produce", None, False),
    ("kappa", "കപ്പ", "cassava tapioca kappa", "tapioca", "20081940", "produce", None, False),
    ("urulakkizhangu", "ഉരുളക്കിഴങ്ങ്", "potato fresh", "potato", "07019000", "produce", None, False),
    ("kumbalanga", "കുമ്പളങ്ങ", "ash gourd white pumpkin", "ash gourd", "07099390", "produce", None, False),
    ("mathanga", "മത്തങ്ങ", "pumpkin orange vegetable", "pumpkin", "07099390", "produce", None, False),
    ("vazhuthananga", "വഴുതനങ്ങ", "brinjal eggplant", "brinjal", "07093000", "produce", None, False),
    ("pavakka", "പാവയ്ക്ക", "bitter gourd karela", "bitter gourd", "07099910", "produce", None, False),
    ("padavalanga", "പടവലങ്ങ", "snake gourd vegetable", "snake gourd", "07099990", "produce", None, False),
    ("cheera", "ചീര", "spinach amaranth leafy", "spinach", "07097000", "produce", None, False),
    ("chembu", "ചേമ്പ്", "taro colocasia", "taro", "07143000", "produce", None, False),
    ("chena", "ചേന", "elephant foot yam", "yam", "07143000", "produce", None, False),
    ("beetroot", "ബീറ്റ്റൂട്ട്", "beetroot red vegetable", "beetroot", "07069000", "produce", None, False),
    ("manga", "മാങ്ങ", "mango raw green", "raw mango", "08045020", "produce", None, False),
    ("naranga", "നാരങ്ങ", "lime lemon citrus", "lime", "08055000", "produce", None, False),
    ("kaithachakka", "കൈതച്ചക്ക", "pineapple fresh fruit", "pineapple", "08043000", "produce", None, False),
    ("kothamalli", "കൊത്തമല്ലി", "coriander leaves fresh", "coriander leaves", "07099990", "produce", None, False),
    ("kariveppila", "കറിവേപ്പില", "curry leaves fresh", "curry leaves", "12119029", "produce", None, False),
    # Souring / pickles
    ("kodampuli", "കൊടംപുളി", "gamboge kodampuli garcinia", "kokum", "08109090", "souring", None, False),
    ("puli inji", "പുളി ഇഞ്ചി", "ginger tamarind pickle inji puli", "inji puli pickle", "20019000", "pickles", "puliinji", False),
    ("inji puli", "ഇഞ്ചി പുളി", "ginger tamarind pickle", "inji puli pickle", "20019000", "pickles", "injipuli", False),
    ("chemmeen achar", "ചെമ്മീൻ അച്ചാർ", "prawn pickle seafood preserved", "prawn pickle", "16055900", "pickles", "chemmeenachar", False),
    ("manga achar", "മാങ്ങ അച്ചാർ", "mango pickle achar", "mango pickle", "20019000", "pickles", "mangaachar", False),
    ("naranga achar", "നാരങ്ങ അച്ചാർ", "lime pickle achar", "lime pickle", "20019000", "pickles", None, False),
    ("meen achar", "മീൻ അച്ചാർ", "fish pickle preserved", "fish pickle", "16041900", "pickles", None, False),
    ("achar", "അച്ചാർ", "pickle preserved vegetable", "pickle", "20019000", "pickles", None, True),
    # Snacks
    ("nendran chips", "നേന്ദ്രൻ ചിപ്സ്", "banana chips plantain fried", "banana chips", "20081990", "snacks", "nendranchips", False),
    ("ethakka chips", "ഏത്തക്ക ചിപ്സ്", "banana chips ethakka plantain", "banana chips", "20081990", "snacks", "ethakkachips", False),
    ("sharkkara upperi", "ശർക്കര ഉപ്പേരി", "jaggery banana chips sweet snack", "jaggery chips", "20081990", "snacks", "sharkkaraupperi", False),
    ("achappam", "അച്ചപ്പം", "rose cookie fried sweet snack", "achappam", "19059090", "snacks", None, False),
    ("murukku", "മുറുക്ക്", "rice lentil snack fried murukku", "murukku", "19059090", "snacks", None, False),
    ("unniyappam", "ഉണ്ണിയപ്പം", "rice sweet fried appam snack", "unniyappam", "19059090", "snacks", None, False),
    ("avalose", "അവലോസ്", "roasted rice powder mix snack", "avalose", "19041090", "snacks", None, False),
    ("parotta", "പരോട്ട", "layered flatbread maida parotta", "parotta", "19059090", "snacks", None, False),
    ("pathiri", "പത്തിരി", "rice flatbread roti pathiri", "pathiri", "19059090", "snacks", None, False),
    # Fish / seafood (retail-safe)
    ("chemmeen", "ചെമ്മീൻ", "prawn shrimp frozen seafood", "prawn", "03061700", "seafood", None, False),
    ("karimeen", "കരിമീൻ", "pearl spot fish fresh water", "pearl spot fish", "03019990", "seafood", None, False),
    ("ayala", "അയല", "mackerel fish indian fresh", "mackerel", "03024200", "seafood", None, False),
    ("mathi", "മത്തി", "sardine fish fresh indian", "sardine", "03025200", "seafood", None, False),
    ("kozhuva", "കൊഴുവ", "anchovy fish dried fresh", "anchovy", "03056900", "seafood", None, False),
    ("njandu", "ഞണ്ട്", "crab crustacean fresh", "crab", "03063300", "seafood", None, False),
    # Household / staples
    ("uppu", "ഉപ്പ്", "salt iodised", "salt", "25010010", "staples", None, False),
    ("chaaya", "ചായ", "tea black leaf", "tea", "09024090", "staples", None, False),
    ("chaya", "ചായ", "tea black leaf", "tea", "09024090", "staples", None, False),
    ("kaapi", "കാപ്പി", "coffee roasted bean", "coffee", "09011100", "staples", None, False),
    ("paal", "പാൽ", "milk fresh", "milk", "04011000", "dairy", None, False),
    ("mutta", "മുട്ട", "egg poultry fresh", "egg", "04070090", "dairy", None, False),
    ("thairu", "തൈര്", "yogurt curd fresh", "curd", "04039090", "dairy", None, False),
    ("puja oil", "പൂജാ എണ്ണ", "lamp oil sesame puja pooja", "puja oil", "15180040", "household", None, False),
    ("pooja oil", "പൂജാ എണ്ണ", "lamp oil sesame puja", "puja oil", "15180040", "household", None, False),
    # Ambiguous standalone (phrase-only safe; no authoritative HSN)
    ("nadan", "നാടൻ", "traditional local country", "traditional local", None, "ambiguous", None, True),
    ("puli", "പുളി", "tamarind pulp sour fruit", "tamarind", None, "ambiguous", None, True),
    ("thuvara", "തുവര", "pigeon pea toor dal", "toor dal", None, "ambiguous", None, True),
    ("unakka", "ഉണക്ക", "dried preserved", "dried", None, "ambiguous", None, True),
]

# Extra OCR / bill variants without full vocabulary rows
OCR_ONLY_ROMAN: list[tuple[str, str, str, str]] = [
    ("mulakupowder", "mulaku podi", "red chilli powder spice", "09042211"),
    ("manjalpowder", "manjal podi", "turmeric powder haldi", "09103010"),
    ("idiyappampodi", "idiyappam podi", "idiyappam rice flour", "11029090"),
    ("sambarpowder", "sambar podi", "sambar masala powder", "09109100"),
    ("rasampowder", "rasam podi", "rasam powder spice", "09109100"),
]


def _entry(
    *,
    language_code: str,
    original_term: str,
    normalized_term: str | None = None,
    english_term: str,
    canonical_query: str,
    hsn_code: str | None,
    category: str,
    priority: int,
    notes: str | None = None,
) -> dict:
    return {
        "language_code": language_code,
        "original_term": original_term,
        "normalized_term": normalized_term or original_term,
        "english_term": english_term,
        "canonical_query": canonical_query,
        "category": category,
        "priority": priority,
        "is_active": True,
        "source_group": SOURCE_GROUP,
        **({"hsn_code": hsn_code} if hsn_code else {}),
        **({"notes": notes} if notes else {}),
    }


def _roman_upper(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).upper()


def build_entries() -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(row: dict) -> None:
        lang = row["language_code"]
        norm = row.get("normalized_term") or row["original_term"]
        hsn = row.get("hsn_code")
        key = (lang, norm if lang == "ml" else _roman_upper(norm), hsn)
        if key in seen:
            return
        seen.add(key)
        out.append(row)

    for item in RESEARCH_VOCABULARY:
        roman, malayalam, english, canonical, hsn, category, ocr, ambiguous = item
        priority = 25 if ambiguous else 100
        notes = "ambiguous standalone - use multi-word retail phrase" if ambiguous else "Kerala retail curated"

        if malayalam:
            add(
                _entry(
                    language_code="ml",
                    original_term=malayalam,
                    english_term=english,
                    canonical_query=canonical,
                    hsn_code=hsn,
                    category=category,
                    priority=priority,
                    notes=notes,
                )
            )
        roman_norm = _roman_upper(roman)
        add(
            _entry(
                language_code="ml-roman",
                original_term=roman_norm,
                normalized_term=roman_norm,
                english_term=english,
                canonical_query=canonical,
                hsn_code=hsn,
                category=category,
                priority=priority,
                notes=notes,
            )
        )
        if ocr:
            add(
                _entry(
                    language_code="ml-roman",
                    original_term=ocr.upper(),
                    normalized_term=ocr.upper(),
                    english_term=english,
                    canonical_query=canonical,
                    hsn_code=hsn,
                    category=category,
                    priority=priority,
                    notes="OCR joined spelling",
                )
            )

    for ocr, spaced, english, hsn in OCR_ONLY_ROMAN:
        add(
            _entry(
                language_code="ml-roman",
                original_term=ocr.upper(),
                english_term=english,
                canonical_query=spaced,
                hsn_code=hsn,
                category="ocr_variant",
                priority=95,
                notes="OCR joined spelling",
            )
        )

    return out


def _row_ambiguous(row: dict) -> bool:
    if int(row.get("priority", 100)) < 50:
        return True
    notes = (row.get("notes") or "").lower()
    return "ambiguous standalone" in notes


def merge_with_existing(new_rows: list[dict]) -> list[dict]:
    """Merge rows; for same (lang, normalized_term) any ambiguous row wins (conservative)."""
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
    else:
        existing = []
    by_term: dict[tuple[str, str], dict] = {}
    for row in list(existing) + list(new_rows):
        lang = row.get("language_code", "ml-roman")
        norm = row.get("normalized_term") or row.get("original_term", "")
        key = (lang, norm)
        prev = by_term.get(key)
        if prev is None:
            by_term[key] = row
            continue
        # Conservative: keep ambiguous / lower-priority when either side is ambiguous.
        if _row_ambiguous(row) or _row_ambiguous(prev):
            if _row_ambiguous(row) and not _row_ambiguous(prev):
                by_term[key] = row
            elif _row_ambiguous(prev) and not _row_ambiguous(row):
                continue
            elif int(row.get("priority", 100)) < int(prev.get("priority", 100)):
                by_term[key] = row
            continue
        if int(row.get("priority", 0)) >= int(prev.get("priority", 0)):
            by_term[key] = row
    merged = list(by_term.values())
    merged.sort(key=lambda r: (r.get("language_code", ""), r.get("original_term", "")))
    return merged


def main() -> int:
    from app.services.kerala_seed import validate_and_normalize_corpus

    rows = merge_with_existing(build_entries())
    normalized, errors = validate_and_normalize_corpus(rows)
    if errors:
        for e in errors[:20]:
            print(f"VALIDATION: {e}", file=sys.stderr)
        if errors:
            return 1
    OUTPUT.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} corpus rows to {OUTPUT} ({len(normalized)} validated)")
    ml = sum(1 for r in rows if r.get("language_code") == "ml")
    roman = sum(1 for r in rows if r.get("language_code") == "ml-roman")
    print(f"  ml={ml} ml-roman={roman}")

    from app.services.kerala_search_policy import analyze_duplicate_corpus_terms

    dup = analyze_duplicate_corpus_terms(rows)
    amb = dup.get("strictly_ambiguous_terms") or []
    if amb:
        print(f"  strictly ambiguous standalone terms ({len(amb)}): {', '.join(amb[:12])}")
        if len(amb) > 12:
            print(f"    ... +{len(amb) - 12} more (see scripts/report_kerala_corpus_policy.py)")
    print("  Next: python scripts/seed_kerala_language_aliases.py  # explicit Neon seed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
