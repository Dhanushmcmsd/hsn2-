import csv
import re
from collections import Counter


def main() -> None:
    path = "data/hsn_codes.csv"
    issues: list[str] = []
    codes_seen: Counter[str] = Counter()

    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, 2):
            raw_code = str(row.get("hsn_code", "")).strip()
            desc = str(row.get("description", "")).strip()
            digits = re.sub(r"[^0-9]", "", raw_code)

            if not digits:
                issues.append(f"Row {index}: Empty/non-numeric HSN code: '{raw_code}'")
            if len(desc) < 3:
                issues.append(f"Row {index}: Description too short: '{desc}' for code '{raw_code}'")
            if desc and re.fullmatch(r"[0-9\s]+", desc):
                issues.append(f"Row {index}: Description appears to be numeric: '{desc}'")
            if digits and len(digits) not in (2, 4, 6, 8):
                issues.append(f"Row {index}: Unusual digit count {len(digits)} for code '{raw_code}'")

            canonical = digits.ljust(8, "0") if digits else raw_code
            codes_seen[canonical] += 1

    duplicates = {code: count for code, count in codes_seen.items() if count > 1}
    if duplicates:
        issues.append(f"DUPLICATES: {duplicates}")

    print(f"Total issues: {len(issues)}")
    for issue in issues[:50]:
        print(issue)


if __name__ == "__main__":
    main()
