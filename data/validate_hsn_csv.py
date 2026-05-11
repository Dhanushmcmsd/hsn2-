import pandas as pd, sys

df = pd.read_csv("data/hsn_codes_full.csv", dtype=str)
assert "hsn_code" in df.columns
assert "description" in df.columns
assert "gst_rate" in df.columns
assert df["hsn_code"].str.match(r"^\d{2,8}$").all(), "Bad HSN codes"
valid_rates = {"0", "5", "12", "18", "28", "3", "0.25"}
bad = df[~df["gst_rate"].isin(valid_rates)]
if not bad.empty:
    print("WARNING: non-standard rates:", bad["gst_rate"].unique())
print(f"Total codes: {len(df)}")
print(df.groupby("gst_rate").size().to_string())
print("Validation passed.")
