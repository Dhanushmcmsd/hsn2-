from __future__ import annotations

import re
from typing import Iterable

# Common Indian trade / retail wording (bidirectional via manual lists).
INDIAN_TRADE_SYNONYMS: dict[str, list[str]] = {
    "broom": ["jhadu", "sweeping brush", "floor brush", "broomstick", "brush broom"],
    "jhadu": ["broom", "sweeping brush", "floor brush", "broomstick"],
    "atta": ["wheat flour", "flour"],
    "besan": ["gram flour", "chickpea flour"],
    "chappal": ["slipper", "sandal", "footwear"],
    "chappals": ["slippers", "sandals", "footwear"],
    "dal": ["lentil", "pulses"],
    "ghee": ["clarified butter"],
    "hing": ["asafoetida"],
    "haldi": ["turmeric"],
    "mirch": ["chilli", "chili", "pepper"],
    "namak": ["salt"],
    "sabun": ["soap"],
    "tel": ["oil"],
    "chini": ["sugar"],
    "doodh": ["milk"],
    "inverter": ["power inverter", "solar inverter"],
}

_MAX_EXPANSIONS = 8


def _ensure_wordnet():
    try:
        import nltk

        nltk.download("wordnet", quiet=True)
        nltk.download("omw-1.4", quiet=True)
    except Exception:
        pass


def _wordnet_expansions(tokens: Iterable[str], seen: set[str], out: list[str]) -> None:
    try:
        from nltk.corpus import wordnet as wn
    except Exception:
        return

    for token in tokens:
        if len(out) >= 1 + _MAX_EXPANSIONS:
            return
        for syn in wn.synsets(token):
            if len(out) >= 1 + _MAX_EXPANSIONS:
                return
            for lemma in syn.lemmas()[:4]:
                name = lemma.name().replace("_", " ").strip().lower()
                if len(name) < 2 or name in seen:
                    continue
                seen.add(name)
                out.append(name)
                if len(out) >= 1 + _MAX_EXPANSIONS:
                    return
            for hyper in syn.hypernyms()[:2]:
                for lemma in hyper.lemmas()[:2]:
                    name = lemma.name().replace("_", " ").strip().lower()
                    if len(name) < 2 or name in seen:
                        continue
                    seen.add(name)
                    out.append(name)
                    if len(out) >= 1 + _MAX_EXPANSIONS:
                        return


def expand_query(term: str) -> list[str]:
    """
    Return the original term plus up to 8 unique expansions from WordNet + Indian trade hints.
    """
    raw = (term or "").strip()
    if not raw:
        return []

    _ensure_wordnet()

    out: list[str] = [raw]
    seen: set[str] = {raw.lower()}

    tokens = [t.lower() for t in re.findall(r"[a-zA-Z\u0080-\u024f]{2,}", raw)]

    for token in tokens:
        if len(out) >= 1 + _MAX_EXPANSIONS:
            break
        for synonym in INDIAN_TRADE_SYNONYMS.get(token, []):
            s = synonym.strip()
            if not s or s.lower() in seen:
                continue
            seen.add(s.lower())
            out.append(s)
            if len(out) >= 1 + _MAX_EXPANSIONS:
                break

    if len(out) < 1 + _MAX_EXPANSIONS:
        _wordnet_expansions(tokens, seen, out)

    return out[: 1 + _MAX_EXPANSIONS]
