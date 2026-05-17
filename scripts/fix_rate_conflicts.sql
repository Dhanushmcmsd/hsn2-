-- Sync verified_products.gst_rate from hsn_master (CBIC-valid rates only).
-- Run against Neon: psql "$DATABASE_URL" -f scripts/fix_rate_conflicts.sql

UPDATE verified_products vp
SET gst_rate = hm.gst_rate::text
FROM hsn_master hm
WHERE vp.hsn_code = hm.hsn_code
  AND (
    vp.gst_rate IS NULL
    OR NULLIF(regexp_replace(vp.gst_rate::text, '[^0-9.]', '', 'g'), '')::numeric
       IS DISTINCT FROM hm.gst_rate::numeric
  )
  AND hm.gst_rate IN (0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28);

-- Remaining mismatches (audit)
SELECT vp.description,
       vp.hsn_code,
       vp.gst_rate AS old_rate,
       hm.gst_rate AS master_rate
FROM verified_products vp
JOIN hsn_master hm ON hm.hsn_code = vp.hsn_code
WHERE vp.gst_rate IS NULL
   OR NULLIF(regexp_replace(vp.gst_rate::text, '[^0-9.]', '', 'g'), '')::numeric
      IS DISTINCT FROM hm.gst_rate::numeric;
