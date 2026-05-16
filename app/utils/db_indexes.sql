-- Performance indexes for HSN search on Neon free tier
-- Run once via psql or any SQL client connected to your Neon DB
-- All statements use IF NOT EXISTS so they are safe to re-run

-- 1. pg_trgm index on verified_products (speeds up L6 verified lookup ~10x)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_vp_desc_norm_trgm
    ON verified_products USING gin (description_normalized gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_vp_no_size_trgm
    ON verified_products USING gin (description_no_size gin_trgm_ops);

-- 2. pg_trgm index on hsn_codes description (speeds up L3 fuzzy ~8x)
CREATE INDEX IF NOT EXISTS idx_hsn_desc_trgm
    ON hsn_codes USING gin (description gin_trgm_ops);

-- 3. Covering index for prefix lookup (L5) — avoids heap fetch
CREATE INDEX IF NOT EXISTS idx_hsn_code_covering
    ON hsn_codes (hsn_code) INCLUDE (description, gst_rate, section_code, hsn_chapter)
    WHERE COALESCE(is_active, TRUE) = TRUE;

-- 4. status index on pending_products (tiny table but used in every admin query)
CREATE INDEX IF NOT EXISTS idx_pending_status
    ON pending_products (status);

-- 5. brand index on verified_products (speeds up brand filter)
CREATE INDEX IF NOT EXISTS idx_verified_brand
    ON verified_products (brand);

-- 6. ANALYSE after bulk seed so planner stats are fresh
ANALYSE verified_products;
ANALYSE hsn_codes;
