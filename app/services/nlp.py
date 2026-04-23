from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProductEntities:
    brand: Optional[str] = None
    product_type: Optional[str] = None
    material: Optional[str] = None
    size: Optional[str] = None
    target: Optional[str] = None
    flavor: Optional[str] = None
    region: Optional[str] = None
    chapter_hint: list[str] = field(default_factory=list)


_TARGET_PATTERNS = {
    r"\b(men['s]*|male|boys?)\b": "mens",
    r"\b(wom[ae]n['s]*|female|girls?|ladies)\b": "womens",
    r"\b(baby|infant|kids?|children['s]*)\b": "baby",
    r"\b(senior|elderly|adult)\b": "adult",
}

_MATERIAL_PATTERNS = {
    r"\b(cotton|polyester|wool|silk|nylon|lycra|spandex)\b": "textile",
    r"\b(stainless\s*steel|ss|inox)\b": "steel",
    r"\b(alumini?um|aluminum)\b": "aluminium",
    r"\b(plastic|pvc|hdpe|ldpe|pp)\b": "plastic",
    r"\b(glass|crystal|borosilicate)\b": "glass",
    r"\b(ceramic|porcelain|earthen)\b": "ceramic",
    r"\b(leather|genuine\s+leather|pu\s+leather)\b": "leather",
    r"\b(wood|wooden|bamboo|teak)\b": "wood",
    r"\b(rubber|silicone|latex)\b": "rubber",
}

_SIZE_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*"
    r"(ml|l|ltr|litre|g|gm|gms|kg|kgs|mg|oz|lb|"
    r"pc|pcs|nos|pieces?|pack|pkt|sachet)\b",
    re.IGNORECASE,
)

_FLAVOR_PATTERNS = {
    r"\b(chocolate|choco|cocoa)\b": "chocolate",
    r"\b(vanilla|vanila|vanl)\b": "vanilla",
    r"\b(strawberry|strbry|strawbry)\b": "strawberry",
    r"\b(mango|alphonso|totapuri)\b": "mango",
    r"\b(mint|menthol|peppermint)\b": "mint",
    r"\b(lemon|lime|nimbu|citrus)\b": "lemon",
    r"\b(jasmine|jasmne|jasmn)\b": "jasmine",
    r"\b(rose|gulab)\b": "rose",
    r"\b(butter\s*scotch|butterscotch)\b": "butterscotch",
    r"\b(coffee|mocha|cappuccino)\b": "coffee",
}

_MATERIAL_CHAPTER_MAP = {
    "textile": ["61", "62", "63"],
    "steel": ["73"],
    "aluminium": ["76"],
    "plastic": ["39"],
    "glass": ["70"],
    "ceramic": ["69"],
    "leather": ["42"],
    "wood": ["44"],
    "rubber": ["40"],
}


def extract_entities(text: str) -> ProductEntities:
    from app.services.matcher import BRANDS, expand_fmcg_abbreviations

    text_lower = text.lower()
    expanded = expand_fmcg_abbreviations(text_lower)

    entities = ProductEntities()

    for brand in BRANDS:
        if re.search(r"\b" + re.escape(brand) + r"\b", text_lower):
            entities.brand = brand
            break

    for pattern, target in _TARGET_PATTERNS.items():
        if re.search(pattern, expanded, re.IGNORECASE):
            entities.target = target
            break

    for pattern, material in _MATERIAL_PATTERNS.items():
        if re.search(pattern, expanded, re.IGNORECASE):
            entities.material = material
            entities.chapter_hint.extend(_MATERIAL_CHAPTER_MAP.get(material, []))
            break

    size_match = _SIZE_PATTERN.search(expanded)
    if size_match:
        entities.size = size_match.group(0).lower()

    for pattern, flavor in _FLAVOR_PATTERNS.items():
        if re.search(pattern, expanded, re.IGNORECASE):
            entities.flavor = flavor
            break

    if re.search(r"\b(kerala|malabar|kodaikanal|coorg)\b", text_lower):
        entities.region = "kerala"
    elif re.search(r"\b(basmati|dehradun|punjab)\b", text_lower):
        entities.region = "north_india"

    return entities


def entities_to_search_boost(entities: ProductEntities) -> dict:
    boost_terms = []

    if entities.target:
        boost_terms.append(entities.target)
    if entities.material:
        boost_terms.append(entities.material)
    if entities.flavor:
        boost_terms.append(entities.flavor)
    if entities.region:
        boost_terms.append(entities.region)

    return {
        "chapter_hints": entities.chapter_hint,
        "boost_terms": boost_terms,
        "has_size": entities.size is not None,
        "brand": entities.brand,
    }
