"""
Seed the Neon PostgreSQL database with HSN/GST master data.
Run once:  python data/seed.py

Requires:  pip install pandas openpyxl sqlalchemy psycopg2-binary
"""
import os, sys
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL") or input("Paste your Neon DATABASE_URL: ").strip()
# Neon URLs start with postgres:// but SQLAlchemy needs postgresql://
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

XLSX = os.path.join(os.path.dirname(__file__), "HSN_GST_Master.xlsx")
if not os.path.exists(XLSX):
    sys.exit(f"File not found: {XLSX}\nPlace HSN_GST_Master.xlsx in the data/ folder.")

print("Reading Excel…")
df = pd.read_excel(XLSX, sheet_name="HSN Master", skiprows=2, header=0)
df.columns = ["hsn_code", "description", "gst_rate", "chapter", "category", "notes"]
df = df.dropna(subset=["hsn_code"])
df["hsn_code"]   = df["hsn_code"].astype(str).str.replace(" ", "").str.strip()
df["gst_rate"]   = df["gst_rate"].fillna(0).astype(float)
df["chapter"]    = df["chapter"].fillna(0).astype(int)
df["notes"]      = df["notes"].fillna("")
df["description"] = df["description"].fillna("").astype(str)
df["category"]   = df["category"].fillna("").astype(str)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS hsn_master (
            id          SERIAL PRIMARY KEY,
            hsn_code    VARCHAR(20) UNIQUE NOT NULL,
            description TEXT,
            gst_rate    NUMERIC(5,2) DEFAULT 0,
            chapter     INT,
            category    VARCHAR(100),
            notes       TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_hsn_code     ON hsn_master(hsn_code);
        CREATE INDEX IF NOT EXISTS idx_hsn_category ON hsn_master(category);
        CREATE INDEX IF NOT EXISTS idx_hsn_rate     ON hsn_master(gst_rate);
    """))
    conn.commit()

print(f"Upserting {len(df)} records…")
for _, row in df.iterrows():
    engine.execute(text("""
        INSERT INTO hsn_master (hsn_code, description, gst_rate, chapter, category, notes)
        VALUES (:hsn_code, :description, :gst_rate, :chapter, :category, :notes)
        ON CONFLICT (hsn_code) DO UPDATE SET
            description = EXCLUDED.description,
            gst_rate    = EXCLUDED.gst_rate,
            chapter     = EXCLUDED.chapter,
            category    = EXCLUDED.category,
            notes       = EXCLUDED.notes
    """), row.to_dict())

print(f"Done — {len(df)} HSN records seeded into {DATABASE_URL.split('@')[1].split('/')[0]}")
