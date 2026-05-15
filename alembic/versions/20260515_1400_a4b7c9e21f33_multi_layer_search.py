"""multi-layer search: language_aliases, search_synonyms, category_taxonomy, hsn_codes section/embedding

Revision ID: a4b7c9e21f33
Revises: f8a91c2d4e10
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op


revision = "a4b7c9e21f33"
down_revision = "f8a91c2d4e10"
branch_labels = None
depends_on = None


_PG_STMTS_UP = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"",
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS fuzzystrmatch",
    "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS section_code VARCHAR(10)",
    "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS search_priority INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE hsn_codes ADD COLUMN IF NOT EXISTS embedding vector(384)",
    "CREATE INDEX IF NOT EXISTS idx_hsn_codes_section ON hsn_codes (section_code)",
    "CREATE INDEX IF NOT EXISTS idx_hsn_codes_chapter ON hsn_codes (hsn_chapter)",
    "CREATE INDEX IF NOT EXISTS idx_hsn_codes_priority ON hsn_codes (search_priority DESC) WHERE search_priority > 0",
    """
    CREATE TABLE IF NOT EXISTS category_taxonomy (
        id SERIAL PRIMARY KEY,
        category_code VARCHAR(8) UNIQUE NOT NULL,
        category_name VARCHAR(150) NOT NULL,
        section_code VARCHAR(10) NOT NULL,
        chapter_range_start INTEGER NOT NULL,
        chapter_range_end INTEGER NOT NULL,
        display_order INTEGER NOT NULL DEFAULT 0,
        official_source VARCHAR(200) NULL,
        description TEXT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_category_taxonomy_section ON category_taxonomy (section_code)",
    """
    CREATE TABLE IF NOT EXISTS language_aliases (
        id SERIAL PRIMARY KEY,
        term TEXT NOT NULL,
        term_normalized TEXT NOT NULL,
        language VARCHAR(8) NOT NULL,
        hsn_code VARCHAR(20) NULL,
        english_term TEXT NULL,
        weight REAL NOT NULL DEFAULT 1.0,
        source VARCHAR(80) NOT NULL DEFAULT 'curated',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_language_alias UNIQUE (term_normalized, language, hsn_code)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_lang_alias_term_norm ON language_aliases (term_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_lang_alias_term_trgm ON language_aliases USING gin (term_normalized gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_lang_alias_hsn ON language_aliases (hsn_code)",
    "CREATE INDEX IF NOT EXISTS idx_lang_alias_lang ON language_aliases (language) WHERE is_active = true",
    "ALTER TABLE language_aliases ADD COLUMN IF NOT EXISTS term_metaphone VARCHAR(16)",
    "ALTER TABLE language_aliases ADD COLUMN IF NOT EXISTS term_dmetaphone VARCHAR(16)",
    "CREATE INDEX IF NOT EXISTS idx_lang_alias_metaphone ON language_aliases (term_metaphone) WHERE is_active = true",
    "CREATE INDEX IF NOT EXISTS idx_lang_alias_dmetaphone ON language_aliases (term_dmetaphone) WHERE is_active = true",
    """
    CREATE TABLE IF NOT EXISTS search_synonyms (
        id SERIAL PRIMARY KEY,
        term TEXT NOT NULL,
        synonym TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 1.0,
        language VARCHAR(8) NOT NULL DEFAULT 'en',
        source VARCHAR(80) NOT NULL DEFAULT 'curated',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_search_synonym UNIQUE (term, synonym, language)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_search_syn_term ON search_synonyms (term) WHERE is_active = true",
    "CREATE INDEX IF NOT EXISTS idx_search_syn_term_trgm ON search_synonyms USING gin (term gin_trgm_ops)",
    "ALTER TABLE search_synonyms ADD COLUMN IF NOT EXISTS term_metaphone VARCHAR(16)",
    "CREATE INDEX IF NOT EXISTS idx_search_syn_metaphone ON search_synonyms (term_metaphone) WHERE is_active = true",
    "ALTER TABLE search_history ADD COLUMN IF NOT EXISTS source VARCHAR(40) NOT NULL DEFAULT 'web'",
    "CREATE INDEX IF NOT EXISTS ix_search_history_query_trgm ON search_history USING gin (query gin_trgm_ops)",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for stmt in _PG_STMTS_UP:
        op.execute(stmt)


def downgrade() -> None:
    # Intentional no-op: this revision is additive (tables, columns, indexes, extensions)
    # and we do not drop data on downgrade for safety.
    pass
