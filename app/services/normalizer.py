"""normalizer.py — product name normalisation.

Changes (2026-05-16):
- Added Malayalam / non-ASCII Unicode passthrough guard.
  Script text (Malayalam, Hindi Devanagari, etc.) must NOT be
  processed by ASCII-only regex patterns.  If the input contains
  non-ASCII characters we return it minimally cleaned so downstream
  search layers (brand_lookup -> language_aliases) can handle it.
"""
from __future__ import annotations

import re
import unicodedata

# ── Constants ─────────────────────────────────────────────────────────────────
_SIZE_UNITS = (
    r'(?:G|GM|GMS|KG|KGS|ML|L|LTR|LITRE|LITER|'
    r'PC|PCS|NOS|NO|N|P|IN|MG|OZ|LB|PACK|PKT|BOX|BTL|BOTTLE|TIN|JAR|CAN|SACHET|BAG|POUCH)'
)
_SIZE_PAT = re.compile(
    rf'\b\d+(?:\.\d+)?\s*{_SIZE_UNITS}\b'
    r'|\b\d+\s*X\s*\d+\b'
    r'|\b\d+\s*\+\s*\d+\b'
    r'|\b\d+S\b|\b\d+N\b|\b\d+P\b',
    re.IGNORECASE,
)

_PUNCT_PAT = re.compile(r'[\(\)\[\]\{\}#@\\|\^~`]')
_WS_PAT = re.compile(r'\s+')

# Characters that indicate non-Latin script (Malayalam, Devanagari, etc.)
_NON_ASCII_RE = re.compile(r'[^\x00-\x7F]')

# Common product words that should NOT be stripped even if they look like brand
_STOP_PREFIXES = frozenset({
    'THE', 'A', 'AN', 'AND', 'WITH', 'FOR', 'OF', 'IN', 'AT', 'BY'
})

# Indian retail POS abbreviations (TallyPrime, Busy, Marg, etc.)
_POS_ABBR_PATTERNS: list[tuple[str, str]] = [
    (r'\bBTL\b', 'BOTTLE'),
    (r'\bPCH\b', 'POUCH'),
    (r'\bPKT\b', 'PACKET'),
    (r'\bSCH\b', 'SACHET'),
    (r'\bSACH\b', 'SACHET'),
    (r'\bCARTON\b', 'CARTON'),
    (r'\bSTRIP\b', 'STRIP'),
    (r'\bTUBE\b', 'TUBE'),
    (r'\bPET\b(?=\s|$)', 'PET BOTTLE'),
    (r'\bHDPE\b', 'HDPE BOTTLE'),
    (r'\bGLASS\b', 'GLASS BOTTLE'),
    (r'\bPDR\b', 'POWDER'),
    (r'\bPWD\b', 'POWDER'),
    (r'\bPOWD\b', 'POWDER'),
    (r'\bLQD\b', 'LIQUID'),
    (r'\bLIQ\b', 'LIQUID'),
    (r'\bCRM\b', 'CREAM'),
    (r'\bLOT\b(?=\s|$)', 'LOTION'),
    (r'\bSPR\b', 'SPRAY'),
    (r'\bOINT\b', 'OINTMENT'),
    (r'\bSYP\b', 'SYRUP'),
    (r'\bTAB\b(?=\s|$)', 'TABLET'),
    (r'\bCAP\b(?=\s|$)', 'CAPSULE'),
    (r'\bINJ\b', 'INJECTION'),
    (r'\bSUSP\b', 'SUSPENSION'),
    (r'\bSOL\b', 'SOLUTION'),
    (r'\bSHP\b', 'SHAMPOO'),
    (r'\bCDNR\b', 'CONDITIONER'),
    (r'\bDTG\b', 'DETERGENT'),
    (r'\bDSH\b', 'DISHWASH'),
    (r'\bFLR\b', 'FLOOR CLEANER'),
    (r'\bDEO\b', 'DEODORANT'),
    (r'\bPRF\b', 'PERFUME'),
    (r'\bFCWSH\b', 'FACE WASH'),
    (r'\bSCRB\b', 'SCRUB'),
    (r'\bMST\b', 'MOISTURISER'),
    (r'\bSNSCRN\b', 'SUNSCREEN'),
    (r'\bLIP\b', 'LIP BALM'),
    (r'\bHCRM\b', 'HAIR CREAM'),
    (r'\bHOIL\b', 'HAIR OIL'),
    (r'\bHGEL\b', 'HAIR GEL'),
    (r'\bTNR\b', 'TONER'),
    (r'\bCRTG\b', 'CARTRIDGE'),
    (r'\bCRT\b(?=\s|$)', 'CARTRIDGE'),
    (r'\bRIBBN\b', 'RIBBON'),
    (r'\bTOOTHPDR\b', 'TOOTH POWDER'),
    (r'\bBIB\b', 'BISCUIT'),
    (r'\bCHOC\b', 'CHOCOLATE'),
    (r'\bCHO\b(?=\s|$)', 'CHOCOLATE'),
    (r'\bCOF\b', 'COFFEE'),
    (r'\bCHAI\b', 'TEA'),
    (r'\bNOOD\b', 'NOODLES'),
    (r'\bVERM\b', 'VERMICELLI'),
    (r'\bNAMK\b', 'NAMKEEN'),
    (r'\bATT\b(?=\s|$)', 'ATTA'),
    (r'\bDL\b(?=\s|$)', 'DAL'),
    (r'\bMSL\b', 'MASALA'),
    (r'\bMSAL\b', 'MASALA'),
    (r'\bRIC\b(?=\s|$)', 'RICE'),
    (r'\bSUGR\b', 'SUGAR'),
    (r'\bSLT\b(?=\s|$)', 'SALT'),
    (r'\bVINGR\b', 'VINEGAR'),
    (r'\bCHUT\b', 'CHUTNEY'),
    (r'\bPICK\b', 'PICKLE'),
    (r'\bKCHP\b', 'KETCHUP'),
    (r'\bMUST\b', 'MUSTARD'),
    (r'\bCHPL\b', 'CHAPPAL'),
    (r'\bSNDL\b', 'SANDAL'),
    (r'\bSLPR\b', 'SLIPPER'),
    (r'\bSHO\b(?=\s|$)', 'SHOE'),
    (r'\bKTCHN\b', 'KITCHEN'),
    (r'\bCKWR\b', 'COOKWARE'),
    (r'\bPRSCKR\b', 'PRESSURE COOKER'),
    (r'\bMBL\b', 'MOBILE'),
    (r'\bCHRGR\b', 'CHARGER'),
    (r'\bEARPH\b', 'EARPHONE'),
    (r'\bHDPH\b', 'HEADPHONE'),
    (r'\bPNDRV\b', 'PEN DRIVE'),
    (r'\bMEMCRD\b', 'MEMORY CARD'),
    (r'\bLPTP\b', 'LAPTOP'),
    (r'\bTBLT\b', 'TABLET'),
    (r'\bCABL\b', 'CABLE'),
    (r'\bAdptr\b', 'ADAPTER'),
    (r'\bWHT\b(?=\s|$)', 'WHEAT'),
    (r'\bGRMT\b', 'GARMENT'),
    (r'\bFBRC\b', 'FABRIC'),
    (r'\bSHRT\b', 'SHIRT'),
    (r'\bPNT\b(?=\s|$)', 'PANT'),
    (r'\bDPR\b', 'DIAPER'),
    (r'\bNTBK\b', 'NOTEBOOK'),
    (r'\bNOTEBK\b', 'NOTEBOOK'),
    (r'\bFLDR\b', 'FOLDER'),
    (r'\bSTAPL\b', 'STAPLER'),
    (r'\bSCSSR\b', 'SCISSORS'),
]

_SIZE_STRIP_PAT = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:KG|GMS|GM|G|ML|LTR|LT|L|PCS|NOS|MTR|M|CM|MM|FT|IN|OZ|LB)\b',
    re.IGNORECASE,
)
_PURE_NUM_PAT = re.compile(r'\b\d+\b')
_MODEL_CODE_PAT = re.compile(r'\b[A-Z]{0,3}\d{2,}[A-Z0-9]{0,4}\b')
_MULT_PAT = re.compile(r'\*|\bX\d+\b|\d+X\b', re.IGNORECASE)

# Bill/OCR typos common on Kerala retail invoices (applied before tokenization)
_RETAIL_TYPO_FIXES: list[tuple[str, str]] = [
    (r"\bCOCUNUT\b", "COCONUT"),
    (r"\bP\s*\.?\s*COCONUT\b", "P COCONUT"),
    (r"\bREFIL\b", "REFILL"),
    (r"\bCOMPUND\b", "COMPOUND"),
    (r"\bBIKIS\b", "BISCUIT"),
    (r"\bHORLICKS\b", "HORLICKS"),
    (r"\bSURF\s+EXCEL\b", "SURF EXCEL"),
    (r"\bEASY\s+WASH\b", "EASY WASH"),
    (r"\bAASHIRVAAD\b", "AASHIRVAAD"),
    (r"\bAASHIRWAD\b", "AASHIRVAAD"),
    (r"\bCLINIC\s*\+\b", "CLINIC PLUS"),
    (r"\bMILK\s+BIKIS\b", "MILK BIKIS"),
    (r"\bPARLE\s*G\b", "PARLE G"),
    (r"\bUDHAYAM\b", "UDAYAM"),
    (r"\bVELLAM\b", "JAGGERY"),
    (r"\bSHARKARA\b", "JAGGERY"),
    (r"\bMATTA\s+RICE\b", "MATTA RICE"),
    (r"\bRICE\s+MATTA\b", "MATTA RICE"),
    (r"\bTOOR\s+DAL\b", "TOOR DAL"),
    (r"\bASAFOETIDA\b", "ASAFOETIDA"),
    (r"\bAPPAM\s+PODI\b", "APPAM PODI"),
    (r"\bCHEMMEEN\s+ACHAR\b", "PICKLED PRAWN"),
    (r"\bBANANA\s+CHIPS\b", "BANANA CHIPS"),
]

_BRAND_FIRST_TOKENS = frozenset({
    'COLGATE', 'PEPSODENT', 'LUX', 'DOVE', 'DETTOL', 'LIFEBUOY', 'SURF', 'ARIEL',
    'TIDE', 'RIN', 'VIM', 'LIZOL', 'HARPIC', 'DOMEX', 'PARACHUTE', 'SAFFOLA', 'FORTUNE', 'AMUL',
    'BRITANNIA', 'PARLE', 'SUNFEAST', 'MAGGI', 'YIPPEE', 'TATA', 'LIPTON', 'NESCAFE', 'BRU',
    'HORLICKS', 'BOURNVITA', 'COMPLAN', 'BOOST', 'MDH', 'EVEREST', 'EASTERN', 'NIRAPARA',
    'VKC', 'LIBERTY', 'PARAGON', 'RELAXO', 'HAWAI', 'ACTION', 'BATA', 'ASIAN', 'NIPPON',
    'PIDILITE', 'FEVICOL', 'REYNOLDS', 'NATRAJ', 'CAMLIN', 'PILOT', 'APSARA',
    'GILLETTE', 'SCHICK', 'MACH', 'WILKINSON', 'BAJAJ', 'PHILIPS', 'HAVELLS', 'SYSKA',
    'GODREJ', 'CELLO', 'MILTON', 'TUPPERWARE', 'PRESTIGE', 'HAWKINS', 'PIGEON', 'BUTTERFLY',
    'GOOD', 'HIDE', 'OREO', 'KIT', 'DAIRY', 'CADBURY', 'NESTLE', 'ITC', 'HUL', 'MARICO',
    'EMAMI', 'HIMALAYA', 'DABUR', 'PATANJALI', 'HAMDARD', 'ZANDU', 'CIPLA', 'SUN', 'DR',
    'RECKITT', 'HENKEL', 'NIRMA', 'GHADI', 'WHEEL', 'GHARI', 'EXIDE', 'AMARON',
    'BOSCH', 'MRF', 'APOLLO', 'CEAT', 'TVS', 'HERO', 'HONDA', 'MARUTI', 'MAHINDRA',
    'SAMSUNG', 'LG', 'SONY', 'NOKIA', 'OPPO', 'VIVO', 'REALME', 'ONEPLUS', 'APPLE', 'MI',
    'HP', 'DELL', 'LENOVO', 'ASUS', 'ACER', 'CANON', 'EPSON', 'BROTHER', 'PANASONIC',
    'ANCHOR', 'FINOLEX', 'POLYCAB', 'CROMPTON', 'USHA', 'ORIENT',
    'MANAK', 'LEMAM', 'ESQUIRE', 'TOY', 'FUNSKOOL', 'LEGO', 'BARBIE', 'NERF', 'CELLO',
})


def _has_script_chars(text: str) -> bool:
    """Return True if text contains non-ASCII (Malayalam/Devanagari/etc.) characters."""
    return bool(_NON_ASCII_RE.search(text))


def fix_retail_typos(text: str) -> str:
    """Fix common OCR / invoice typos on ASCII retail product names."""
    if not text or _has_script_chars(text):
        return text
    out = text.upper()
    for pattern, replacement in _RETAIL_TYPO_FIXES:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def expand_pos_abbreviations(text: str) -> str:
    """Expand Indian retail POS abbreviations before matching."""
    if not text:
        return ''
    out = fix_retail_typos(text)
    out = out.upper()
    for pattern, replacement in _POS_ABBR_PATTERNS:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def strip_noise_tokens(text: str) -> str:
    """Remove sizes, model codes, and pure numbers; keep product-type words."""
    if not text:
        return ''
    out = expand_pos_abbreviations(text)
    out = _SIZE_STRIP_PAT.sub(' ', out)
    out = _PURE_NUM_PAT.sub(' ', out)
    out = _MODEL_CODE_PAT.sub(' ', out)
    out = _MULT_PAT.sub(' ', out)
    out = _WS_PAT.sub(' ', out).strip().upper()
    return out


def extract_product_keywords(text: str) -> list[str]:
    """Extract 1–3 product-type keywords after POS expansion and noise stripping."""
    cleaned = strip_noise_tokens(text)
    if not cleaned:
        return []
    tokens = cleaned.split()
    if not tokens:
        return []
    while tokens and tokens[0] in _BRAND_FIRST_TOKENS:
        tokens = tokens[1:]
    if not tokens:
        tokens = cleaned.split()[-2:]
    # Product type is usually the last token(s) after brand + marketing words
    if len(tokens) >= 2:
        tail = tokens[-2:]
        if len(tail[-1]) >= 5:
            return [tail[-1]]
        return [' '.join(tail)]
    return tokens[:1]


def normalize_product_name(raw: str) -> str:
    """
    Normalize a raw product description for HSN search.

    Strategy
    --------
    1. If the input contains non-ASCII script characters (Malayalam, Hindi,
       Arabic, etc.) — return it as-is after minimal whitespace cleanup.  The
       language_aliases / kerala_search layers handle script text directly.
    2. For ASCII/Latin text: strip size/unit tokens, collapse whitespace,
       upper-case.  Preserve brand names and descriptive words.
    """
    if not raw:
        return ''

    text = expand_pos_abbreviations(raw.strip())

    # ── Guard: non-ASCII / script input — pass through unchanged ──────────────
    if _has_script_chars(text):
        # Only collapse whitespace; preserve every non-ASCII character exactly
        return _WS_PAT.sub(' ', text).strip()

    # ── ASCII / Latin normalisation path ──────────────────────────────────────
    text = strip_noise_tokens(text)
    # 1. Remove packaging punctuation (brackets, special chars)
    text = _PUNCT_PAT.sub(' ', text)

    # 2. Strip size/quantity tokens  (e.g. "500G", "2X200ML", "3+1")
    text = _SIZE_PAT.sub(' ', text)

    # 3. Collapse whitespace and upper-case
    text = _WS_PAT.sub(' ', text).strip().upper()

    # 4. Remove leading stop words ("A ", "THE ") but keep brand first-words
    tokens = text.split()
    # Only strip if the token is a stop word AND there are more tokens after it
    while tokens and tokens[0] in _STOP_PREFIXES and len(tokens) > 1:
        tokens = tokens[1:]

    return ' '.join(tokens)
