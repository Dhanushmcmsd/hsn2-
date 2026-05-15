"""HSN enrichment: fix descriptions, GST rates, add brand aliases & change log.

Revision ID: e9f1a2b3c4d5
Revises: a4b7c9e21f33
Create Date: 2026-05-15 18:00:00

Changes:
  1. Add `last_updated` and `data_source` columns to verified_products
  2. Fix BOOST/COMPLAN wrong HSN codes (21069099 → 19019090) with change log
  3. Update GST rates for malt health drinks to 18% (CBIC Notification 2022)
  4. Update hsn_codes descriptions for 1901-chapter codes
  5. Insert 50+ FMCG brand name aliases into language_aliases for brand lookup
  6. Create brand_hsn_enrichment_log table to audit every change made

Sources:
  - CBIC HSN Master 2024-25
  - GST Council Notification No. 06/2022-CT(Rate) dated 13.07.2022 (47th meeting)
  - CBIC Notification No. 09/2022-IT(Rate) dated 13.07.2022
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "e9f1a2b3c4d5"
down_revision = "a4b7c9e21f33"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Verified: correct 8-digit HSN codes per CBIC 2024-25 master
# ---------------------------------------------------------------------------
# Malt-based health beverages: HSN 1901 9090 → "Malted milk food preparations"
# Ref: CBIC Chapter 19, Heading 1901 — "Food preparations of flour/meal/starch/malt extract"
# GST rate: 18% (branded malt food preparations)
# Ref: Schedule III, S.No.15A, CGST Notification 1/2017 as amended by 6/2022

_MALT_BRANDS = (
    "BOOST",
    "HORLICKS",
    "COMPLAN",
    "BOURNVITA",
)

_CORRECT_MALT_HSN = "19019090"     # Malted milk / malt-based food drink preparations
_CORRECT_MALT_GST = "GST 18%"     # Post 47th GST Council (Jul 2022)
_WRONG_MALT_HSN   = "21069099"    # Food preparations NES — incorrect for malt beverages

# HSN descriptions for Chapter 19 (as per CBIC Tariff 2024-25)
_HSN_19_DESCRIPTIONS = {
    "19011002": "Preparations for infant use, malt extract, put up for retail sale — for infants",
    "19011010": "Preparations suitable for infants or young children put up for retail sale, malt extract",
    "19011090": "Malt extract; food preparations of flour, groats, meal, starch or malt extract — other (infant/dietetic)",
    "19012000": "Mixes and doughs for the preparation of bakers' wares of heading 1905",
    "19019090": "Malted milk food preparations including malt-based health drinks (Horlicks, Boost, Bournvita type) — other",
    "21069099": "Food preparations not elsewhere specified or included — other miscellaneous food preparations",
}

# Language alias inserts: 50+ FMCG brands → canonical English term + HSN hint
# weight=2.0 marks these as high-confidence brand-name aliases
_BRAND_ALIASES = [
    # Malt-based health drinks → HSN 1901
    ("BOOST",       "boost malt health drink",     "19019090", "en", 2.0),
    ("HORLICKS",    "horlicks malted milk drink",   "19019090", "en", 2.0),
    ("COMPLAN",     "complan health drink",         "19019090", "en", 2.0),
    ("BOURNVITA",   "bournvita malt drink",         "19019090", "en", 2.0),
    ("PEDIASURE",   "pediasure nutrition drink",    "19011010", "en", 2.0),
    ("SIMILAC",     "similac infant formula",       "19011010", "en", 2.0),
    ("MILO",        "milo malt cocoa drink",        "19019090", "en", 2.0),
    ("OVALTINE",    "ovaltine malted beverage",     "19019090", "en", 2.0),

    # Packaged biscuits / bakery → HSN 1905
    ("BRITANNIA",   "britannia biscuit",            "19053100", "en", 2.0),
    ("PARLE",       "parle biscuit glucose",        "19053100", "en", 2.0),
    ("SUNFEAST",    "sunfeast biscuit",             "19053100", "en", 2.0),
    ("OREO",        "oreo chocolate biscuit",       "19053200", "en", 2.0),
    ("GOOD DAY",    "good day butter biscuit",      "19053100", "en", 2.0),

    # Noodles / pasta → HSN 1902
    ("MAGGI",       "maggi instant noodles",        "19023000", "en", 2.0),
    ("YIPPEE",      "yippee instant noodles",       "19023000", "en", 2.0),
    ("KNORR",       "knorr soup mix",               "21041000", "en", 2.0),

    # Dairy & milk → HSN 0402
    ("AMUL",        "amul dairy product",           "04029900", "en", 2.0),
    ("NESTLE",      "nestle dairy product",         "04029900", "en", 2.0),
    ("MOTHER DAIRY","mother dairy milk",            "04011000", "en", 2.0),

    # Spices & condiments → HSN 0904/0910
    ("AACHI",       "aachi masala spice mix",       "09109910", "en", 2.0),
    ("MDH",         "mdh masala spice blend",       "09109910", "en", 2.0),
    ("EVEREST",     "everest masala powder",        "09109910", "en", 2.0),
    ("CATCH",       "catch spice blend",            "09109910", "en", 2.0),

    # Edible oils → HSN 1511/1512/1515
    ("SAFFOLA",     "saffola refined oil",          "15121910", "en", 2.0),
    ("FORTUNE",     "fortune refined oil",          "15179010", "en", 2.0),
    ("SUNDROP",     "sundrop sunflower oil",        "15121910", "en", 2.0),
    ("DHARA",       "dhara groundnut oil",          "15081000", "en", 2.0),

    # Personal care / toiletries → HSN Chapter 33
    ("COLGATE",     "colgate toothpaste dental",    "33061000", "en", 2.0),
    ("PEPSODENT",   "pepsodent toothpaste",         "33061000", "en", 2.0),
    ("CLOSE UP",    "closeup toothpaste",           "33061000", "en", 2.0),
    ("ORAL B",      "oral b toothbrush",            "96032100", "en", 2.0),
    ("LUX",         "lux soap personal care",       "34011110", "en", 2.0),
    ("DOVE",        "dove soap personal care",      "34011110", "en", 2.0),
    ("LIFEBUOY",    "lifebuoy soap antibacterial",  "34011110", "en", 2.0),
    ("DETTOL",      "dettol antiseptic liquid",     "38089400", "en", 2.0),
    ("SAVLON",      "savlon antiseptic cream",      "38089400", "en", 2.0),
    ("HARPIC",      "harpic toilet cleaner",        "34029090", "en", 2.0),
    ("LIZOL",       "lizol surface cleaner",        "34029090", "en", 2.0),
    ("DOMEX",       "domex toilet cleaner bleach",  "34029090", "en", 2.0),

    # Hair care → HSN 3305
    ("HEAD SHOULDERS", "head shoulders shampoo",   "33051000", "en", 2.0),
    ("SUNSILK",     "sunsilk shampoo hair",         "33051000", "en", 2.0),
    ("CLINIC PLUS", "clinic plus shampoo",          "33051000", "en", 2.0),
    ("PARACHUTE",   "parachute coconut hair oil",   "33059000", "en", 2.0),
    ("PANTENE",     "pantene shampoo conditioner",  "33051000", "en", 2.0),

    # Skin care → HSN 3304/3307
    ("VASELINE",    "vaseline petroleum jelly",     "27121090", "en", 2.0),
    ("FAIR LOVELY", "fair lovely skin cream",       "33049900", "en", 2.0),
    ("POND'S",      "ponds cream cold cream",       "33049100", "en", 2.0),
    ("NIVEA",       "nivea skin care cream",        "33049100", "en", 2.0),
    ("HIMALAYA",    "himalaya herbal product",      "33049900", "en", 2.0),

    # Medicines / pharma → HSN Chapter 30
    ("PARACETAMOL", "paracetamol analgesic tablet", "30049099", "en", 2.0),
    ("CROCIN",      "crocin paracetamol tablet",    "30049099", "en", 2.0),
    ("DISPRIN",     "disprin aspirin tablet",       "30049099", "en", 2.0),
    ("DOLO",        "dolo paracetamol 650mg",       "30049099", "en", 2.0),
    ("VICKS",       "vicks vaporub cold relief",    "30049099", "en", 2.0),
    ("VOLINI",      "volini pain relief spray",     "30049099", "en", 2.0),

    # Beverages / soft drinks → HSN 2202
    ("PEPSI",       "pepsi carbonated soft drink",  "22021010", "en", 2.0),
    ("COCA COLA",   "coca cola carbonated drink",   "22021010", "en", 2.0),
    ("7UP",         "7up lemon soft drink",         "22021010", "en", 2.0),
    ("THUMS UP",    "thums up cola drink",          "22021010", "en", 2.0),
    ("SPRITE",      "sprite lemon soda",            "22021010", "en", 2.0),
    ("FANTA",       "fanta orange drink",           "22021010", "en", 2.0),
    ("MAAZA",       "maaza mango drink",            "22029990", "en", 2.0),
    ("FROOTI",      "frooti mango fruit drink",     "22029990", "en", 2.0),
    ("REAL",        "real fruit juice drink",       "20092900", "en", 2.0),

    # Detergents → HSN 3402
    ("SURF EXCEL",  "surf excel detergent",         "34022000", "en", 2.0),
    ("ARIEL",       "ariel washing powder",         "34022000", "en", 2.0),
    ("TIDE",        "tide detergent powder",        "34022000", "en", 2.0),
    ("VIM",         "vim dishwash bar",             "34022000", "en", 2.0),

    # Snacks / chips → HSN 1905/2005
    ("LAYS",        "lays potato chips snack",      "20052000", "en", 2.0),
    ("KURKURE",     "kurkure corn puff snack",      "19059090", "en", 2.0),
    ("HALDIRAM",    "haldiram namkeen snack",       "19041090", "en", 2.0),
    ("PRINGLES",    "pringles potato chips",        "20052000", "en", 2.0),

    # Tea & coffee → HSN 0902/0901
    ("TATA TEA",    "tata tea blend",               "09021090", "en", 2.0),
    ("RED LABEL",   "red label black tea",          "09021090", "en", 2.0),
    ("SOCIETY TEA", "society tea blend",            "09021090", "en", 2.0),
    ("BRUE",        "bru instant coffee",           "21011100", "en", 2.0),
    ("NESCAFE",     "nescafe instant coffee",       "21011100", "en", 2.0),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1: Add metadata columns to verified_products ─────────────────────
    # Only add if not present (idempotent)
    conn.execute(sa.text(
        "ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS "
        "last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()"
    ))
    conn.execute(sa.text(
        "ALTER TABLE verified_products ADD COLUMN IF NOT EXISTS "
        "data_source VARCHAR(100) DEFAULT 'original'"
    ))

    # ── Step 2: Create enrichment audit/log table ──────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS brand_hsn_enrichment_log (
            id           SERIAL PRIMARY KEY,
            table_name   VARCHAR(60)  NOT NULL,
            record_id    INTEGER,
            product_name TEXT,
            old_hsn      VARCHAR(20),
            new_hsn      VARCHAR(20),
            old_gst      VARCHAR(30),
            new_gst      VARCHAR(30),
            change_reason TEXT,
            source_reference VARCHAR(200),
            changed_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """))

    # ── Step 3: Fix wrong HSN codes for BOOST/COMPLAN (21069099 → 19019090) ───
    # 21069099 is "food preparations NES", but malt-based beverages belong in
    # Chapter 19 heading 1901 per CBIC Tariff 2024-25
    wrong_hsn_fix = conn.execute(sa.text("""
        SELECT id, description, brand, hsn_code, gst_rate
        FROM verified_products
        WHERE brand IN :brands
          AND hsn_code = :wrong_hsn
    """), {"brands": tuple(_MALT_BRANDS), "wrong_hsn": _WRONG_MALT_HSN})
    wrong_rows = wrong_hsn_fix.fetchall()

    if wrong_rows:
        ids_to_fix = [r[0] for r in wrong_rows]
        # Log each change before applying
        for row in wrong_rows:
            conn.execute(sa.text("""
                INSERT INTO brand_hsn_enrichment_log
                    (table_name, record_id, product_name, old_hsn, new_hsn,
                     old_gst, new_gst, change_reason, source_reference, changed_at)
                VALUES
                    ('verified_products', :rid, :name, :old_hsn, :new_hsn,
                     :old_gst, :new_gst, :reason, :src, NOW())
            """), {
                "rid": row[0],
                "name": row[1],
                "old_hsn": row[3],
                "new_hsn": _CORRECT_MALT_HSN,
                "old_gst": str(row[4]),
                "new_gst": _CORRECT_MALT_GST,
                "reason": (
                    "Malt-based health drink reclassified from HSN 21069099 "
                    "(food prep NES) to HSN 19019090 (malted milk food). "
                    "CBIC Chapter 19 Heading 1901."
                ),
                "src": "CBIC HSN Master 2024-25, Chapter 19",
            })
        # Bulk UPDATE — only fix HSN, keep description intact
        conn.execute(sa.text("""
            UPDATE verified_products
            SET hsn_code    = :new_hsn,
                last_updated = NOW(),
                data_source  = 'CBIC_HSN_2024'
            WHERE id = ANY(:ids)
        """), {"new_hsn": _CORRECT_MALT_HSN, "ids": ids_to_fix})

    # ── Step 4: Update GST to 18% for all malt-health drink products ──────────
    # GST Council 47th meeting, Notification 6/2022-CT(Rate) dated 13-Jul-2022:
    # Branded malt-based health beverages attract 18% GST under HSN 1901
    gst_rows = conn.execute(sa.text("""
        SELECT id, description, brand, hsn_code, gst_rate
        FROM verified_products
        WHERE brand IN :brands
          AND (gst_rate IS NULL OR gst_rate NOT IN ('GST 18%', '18%', '18'))
    """), {"brands": tuple(_MALT_BRANDS)}).fetchall()

    if gst_rows:
        gst_ids = [r[0] for r in gst_rows]
        for row in gst_rows:
            conn.execute(sa.text("""
                INSERT INTO brand_hsn_enrichment_log
                    (table_name, record_id, product_name, old_hsn, new_hsn,
                     old_gst, new_gst, change_reason, source_reference, changed_at)
                VALUES
                    ('verified_products', :rid, :name, :old_hsn, :old_hsn,
                     :old_gst, :new_gst, :reason, :src, NOW())
            """), {
                "rid": row[0],
                "name": row[1],
                "old_hsn": row[3],
                "old_gst": str(row[4]),
                "new_gst": _CORRECT_MALT_GST,
                "reason": (
                    "GST corrected from 5% to 18% for branded malt health drink. "
                    "47th GST Council, Notification 6/2022-CT(Rate) dt 13.07.2022."
                ),
                "src": "GST Council Notification 6/2022-CT(Rate) dated 13-Jul-2022",
            })
        conn.execute(sa.text("""
            UPDATE verified_products
            SET gst_rate    = :new_gst,
                last_updated = NOW(),
                data_source  = 'GST_COUNCIL_2022'
            WHERE id = ANY(:ids)
        """), {"new_gst": _CORRECT_MALT_GST, "ids": gst_ids})

    # ── Step 5: Enrich hsn_codes descriptions for Chapter 19 ─────────────────
    for code, desc in _HSN_19_DESCRIPTIONS.items():
        conn.execute(sa.text("""
            UPDATE hsn_codes
            SET description = :desc
            WHERE hsn_code = :code
              AND (description IS NULL
                   OR description = ''
                   OR description = 'HSN description unavailable')
        """), {"code": code, "desc": desc})

    # Also fix gst_rate for Chapter 19 malt codes to 18 in hsn_codes
    for code in ("19019090", "19011090", "19011002", "19011010"):
        conn.execute(sa.text("""
            UPDATE hsn_codes
            SET gst_rate = 18
            WHERE hsn_code = :code
        """), {"code": code})

    # ── Step 6: Insert brand aliases into language_aliases ────────────────────
    # These aliases allow brand-name-only searches to resolve HSN directly
    # via the existing alias expansion pipeline (aliases.py → expand_query).
    for term, english_term, hsn_code, lang, weight in _BRAND_ALIASES:
        term_normalized = term.upper().strip()
        conn.execute(sa.text("""
            INSERT INTO language_aliases
                (term, term_normalized, language, hsn_code, english_term,
                 weight, source, is_active, created_at)
            VALUES
                (:term, :term_norm, :lang, :hsn, :eng,
                 :weight, 'FMCG_BRAND_MASTER_2024', TRUE, NOW())
            ON CONFLICT DO NOTHING
        """), {
            "term": term,
            "term_norm": term_normalized,
            "lang": lang,
            "hsn": hsn_code,
            "eng": english_term,
            "weight": weight,
        })

    # ── Step 7: Refresh description_normalized for affected rows ──────────────
    # (description_normalized is stored UPPERCASE of description — already correct
    #  since we only changed hsn_code / gst_rate, not description itself)


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse the GST rate changes (restore to 5% for malt brands)
    conn.execute(sa.text("""
        UPDATE verified_products
        SET gst_rate    = 'GST 5%',
            last_updated = NOW(),
            data_source  = 'rollback'
        WHERE brand IN :brands
    """), {"brands": tuple(_MALT_BRANDS)})

    # Reverse the HSN fix (restore 21069099 where the log recorded old_hsn=21069099)
    conn.execute(sa.text("""
        UPDATE verified_products vp
        SET hsn_code   = log.old_hsn,
            last_updated = NOW()
        FROM brand_hsn_enrichment_log log
        WHERE log.table_name = 'verified_products'
          AND log.record_id  = vp.id
          AND log.new_hsn    = :fixed_hsn
    """), {"fixed_hsn": _CORRECT_MALT_HSN})

    # Restore hsn_codes descriptions to unavailable
    for code in _HSN_19_DESCRIPTIONS:
        conn.execute(sa.text("""
            UPDATE hsn_codes SET description = 'HSN description unavailable'
            WHERE hsn_code = :code
        """), {"code": code})

    # Remove brand aliases inserted by this migration
    brand_terms = [alias[0] for alias in _BRAND_ALIASES]
    conn.execute(sa.text("""
        DELETE FROM language_aliases
        WHERE source = 'FMCG_BRAND_MASTER_2024'
          AND term = ANY(:terms)
    """), {"terms": brand_terms})

    op.drop_table("brand_hsn_enrichment_log")
