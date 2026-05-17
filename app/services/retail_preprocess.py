"""Single source of truth for Kerala/Malayalam retail query preprocessing.

Used by classify(), predict(), and client Excel smoke tests. Expansion and
normalization only — does not perform fuzzy HSN matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.kerala_aliases import KERALA_ABBREVIATIONS
from app.services.matcher import expand_fmcg_abbreviations, strip_sizes, tokenize
from app.services.normalizer import fix_retail_typos, normalize_product_name

# Romanized Malayalam → English search terms (longest match first at runtime)
MALAYALAM_TRANSLITERATIONS: dict[str, str] = {
    "payar": "cowpea beans legume",
    "cheera": "spinach amaranth leafy",
    "chena": "yam elephant foot",
    "chembu": "taro colocasia",
    "muringakka": "drumstick moringa pods",
    "pavakka": "bitter gourd karela",
    "kumbalanga": "ash gourd white pumpkin",
    "mathanga": "pumpkin orange",
    "vazhuthananga": "brinjal eggplant",
    "tomato": "tomato fresh vegetable",
    "beetroot": "beetroot red vegetable",
    "chakka": "jackfruit tropical",
    "vazhakka": "plantain banana raw",
    "ethakka": "nendran banana cooking",
    "manga": "mango raw green",
    "naranga": "lime lemon citrus",
    "nellikka": "amla gooseberry",
    "kudampuli": "gamboge kokum",
    "mathi": "sardine fish",
    "ayala": "mackerel fish",
    "karimeen": "pearl spot fish",
    "vaval": "pomfret fish",
    "chemmeen": "prawn shrimp",
    "njandu": "crab crustacean",
    "kozhuva": "anchovy fish",
    "kalava": "grouper reef fish",
    "konchu": "lobster prawn seafood",
    "cherupayar": "green gram moong",
    "vanpayar": "cowpea red beans",
    "uzhunnu": "urad black gram",
    "kadala": "chana chickpea black",
    "kanji": "rice gruel porridge",
    "ulli": "onion shallot",
    "savola": "onion shallot",
    "inchi": "ginger fresh",
    "veluthulluli": "garlic cloves",
    "kurumulaku": "black pepper whole",
    "mulaku": "chilli pepper dry red",
    "jeerakam": "cumin jeera seeds",
    "dhania": "coriander seeds",
    "manjal": "turmeric haldi",
    "patta": "cinnamon stick bark",
    "grambu": "cloves whole spice",
    "jathikka": "nutmeg seed spice",
    "thean": "honey natural bee",
    "nallenna": "sesame gingelly oil",
    "thenganna": "coconut oil edible",
    "unniyappam": "rice sweet fried appam",
    "aluva": "sweet halwa alwa",
    "ada": "rice payasam ingredient",
    "palpayasam": "milk rice kheer payasam",
    "kalathappam": "rice cake steamed",
    "unnakai": "banana sweet fritter",
    "achappam": "rose cookie fried sweet",
    "murukku": "rice lentil snack fried",
    "avalose": "roasted rice powder mix",
    "coir": "coconut fibre rope mat",
    "cpra": "copra dried coconut",
    "beedi": "bidi tobacco leaf rolled",
    "parotta": "layered flatbread maida",
    "pathiri": "rice flatbread roti",
    "manjal podi": "turmeric powder haldi",
    "chaaya": "tea black leaf",
    "chaya": "tea black leaf",
    "chaaya podi": "tea powder black",
    "chaya podi": "tea powder black",
    "vellam": "jaggery gur",
    "sharkara": "jaggery sugar",
    "appam podi": "appam idiyappam rice flour batter",
    "achar": "pickle preserved",
    "puttu": "puttu rice flour steamed",
    "aval": "beaten rice poha",
    "matta": "matta rice rosematta",
    "kappa": "tapioca cassava",
    "sambar podi": "sambar masala powder",
    "rasam podi": "rasam powder spice",
    "puja oil": "lamp oil sesame puja",
    "pooja oil": "lamp oil sesame puja",
    "pathimukham": "sarsaparilla herbal",
    "nadan": "traditional local country",
    "mulaku podi": "red chilli powder spice",
    "kaapi podi": "coffee powder roasted instant",
    "kaayam": "asafoetida hing powder",
    "sarkara": "jaggery sugar gur",
    "velichenna": "coconut oil edible",
    "vellachenna": "coconut oil edible",
    "thenga": "coconut fresh kernel",
    "kaduku": "mustard seeds rai",
    "uluva": "fenugreek methi seeds",
    "perumjeerakam": "fennel seeds saunf",
    "puzhukkalari": "parboiled rice kerala",
    "matta ari": "matta rice rosematta red",
    "pacha ari": "raw rice paddy grain",
    "nadan ari": "traditional local country rice",
    "puttu podi": "puttu rice flour steamed",
    "ragi podi": "ragi finger millet flour",
    "chemmeen achar": "prawn pickle seafood preserved",
    "nendran chips": "banana chips plantain fried",
    "ethakka chips": "banana chips ethakka plantain",
    "sharkkara upperi": "jaggery banana chips sweet snack",
    "thuvara parippu": "pigeon pea toor dal split",
    "kadala mavu": "chickpea flour besan gram",
    "vellari": "cucumber fresh vegetable",
    "thakkali": "tomato fresh vegetable",
    "vendakka": "okra ladyfinger vegetable",
    "cheriyulli": "shallot small onion",
    "ellu": "sesame seeds til",
    "kodampuli": "gamboge kodampuli garcinia",
    "unakka mulaku": "dry red chilli whole dried",
    "puli": "tamarind pulp sour",
    "uzhunu": "urad black gram dal",
    "thuvara": "pigeon pea toor dal",
    "unakka": "dried preserved",
}

# Bill/OCR joined spellings → spaced retail forms (longest first at runtime)
_KERALA_JOINED_FORMS: tuple[tuple[str, str], ...] = (
    ("manjalpodi", "manjal podi"),
    ("chaayapodi", "chaya podi"),
    ("chayapodi", "chaya podi"),
    ("mulakupodi", "mulaku podi"),
    ("kaapipodi", "kaapi podi"),
    ("puttupodi", "puttu podi"),
    ("appampodi", "appam podi"),
    ("ragipodi", "ragi podi"),
    ("vellachenna", "velichenna"),
    ("nendranchips", "nendran chips"),
    ("ethakkachips", "ethakka chips"),
    ("sharkkaraupperi", "sharkkara upperi"),
    ("kadalamavu", "kadala mavu"),
    ("thuvaraparippu", "thuvara parippu"),
    ("mattaari", "matta ari"),
    ("pachari", "pacha ari"),
    ("nadanari", "nadan ari"),
    ("puzhukkalari", "puzhukkalari"),
    ("chemmeenachar", "chemmeen achar"),
    ("unakkamulaku", "unakka mulaku"),
)


def _split_joined_kerala_compounds(text_value: str) -> str:
    """Insert spaces into common joined Kerala retail spellings before expansion."""
    lower = text_value.lower()
    for joined, spaced in sorted(_KERALA_JOINED_FORMS, key=lambda x: len(x[0]), reverse=True):
        if joined in lower:
            pattern = re.compile(re.escape(joined), re.IGNORECASE)
            lower = pattern.sub(spaced, lower)
    return lower


def _normalize_ws(text_value: str) -> str:
    return re.sub(r"\s+", " ", text_value.strip().upper())


def apply_kerala_expansion(query: str) -> str:
    """Kerala invoice + romanized Malayalam expansion (in-memory, no DB)."""
    query = _split_joined_kerala_compounds(query)
    normalized = _normalize_ws(query)
    expanded = normalized

    for raw, replacement in sorted(
        KERALA_ABBREVIATIONS.items(), key=lambda x: len(x[0]), reverse=True
    ):
        pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(raw.upper())}(?![A-Z0-9])")
        expanded = pattern.sub(replacement.upper(), expanded)

    expanded = expand_fmcg_abbreviations(expanded).upper()

    lower_expanded = expanded.lower()
    for mal_word, english_equiv in sorted(
        MALAYALAM_TRANSLITERATIONS.items(), key=lambda x: len(x[0]), reverse=True
    ):
        pattern = re.compile(rf"\b{re.escape(mal_word.lower())}\b")
        if pattern.search(lower_expanded):
            lower_expanded = pattern.sub(english_equiv.lower(), lower_expanded)

    expanded = lower_expanded.upper()
    return _normalize_ws(strip_sizes(expanded))


def expand_kerala_query(query: str) -> str:
    """Backward-compatible alias used across the codebase."""
    return apply_kerala_expansion(query)


@dataclass
class RetailPreprocessResult:
    original: str
    normalized: str
    typo_fixed: str
    malayalam_expanded: str
    canonical: str
    retail_tokens: list[str] = field(default_factory=list)
    kerala_applied: bool = False
    detected_language: str = "en"
    for_classify: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "typo_fixed": self.typo_fixed,
            "malayalam_expanded": self.malayalam_expanded,
            "canonical": self.canonical,
            "retail_tokens": self.retail_tokens,
            "kerala_applied": self.kerala_applied,
            "detected_language": self.detected_language,
            "for_classify": self.for_classify,
        }


def preprocess_retail_query(query: str, *, for_classify: bool = False) -> RetailPreprocessResult:
    """Normalize, fix OCR typos, and apply Kerala/Malayalam expansion."""
    original = (query or "").strip()
    if not original:
        return RetailPreprocessResult(
            original="",
            normalized="",
            typo_fixed="",
            malayalam_expanded="",
            canonical="",
            for_classify=for_classify,
        )

    from app.services.aliases import detect_language

    detected = detect_language(original)
    typo_fixed = fix_retail_typos(_split_joined_kerala_compounds(original))
    normalized_name = normalize_product_name(typo_fixed)
    normalized = _normalize_ws(normalized_name if normalized_name else typo_fixed)

    before_kerala = normalized
    malayalam_expanded = apply_kerala_expansion(typo_fixed)
    kerala_applied = malayalam_expanded != before_kerala

    canonical = malayalam_expanded
    retail_tokens = tokenize(canonical)

    return RetailPreprocessResult(
        original=original,
        normalized=normalized,
        typo_fixed=_normalize_ws(typo_fixed) if typo_fixed else normalized,
        malayalam_expanded=malayalam_expanded,
        canonical=canonical,
        retail_tokens=retail_tokens,
        kerala_applied=kerala_applied,
        detected_language=detected,
        for_classify=for_classify,
    )
