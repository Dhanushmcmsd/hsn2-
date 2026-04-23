import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.hsn_master import _read_xlsx_rows


CHAPTER_CHECKS = [
    (["tooth", "paste", "toothpaste"], ["33"], "Toothpaste must be Ch33"),
    (["shampoo", "conditioner"], ["33"], "Shampoo must be Ch33"),
    (["footwear", "sandal", "slipper", "chappal", "shoe"], ["64"], "Footwear must be Ch64"),
    (["biscuit", "cookie", "wafer"], ["19"], "Biscuit must be Ch19"),
    (["rice", "basmati", "matta"], ["10"], "Rice must be Ch10"),
    (["flour", "atta", "maida"], ["10", "11"], "Flour must be Ch10/11"),
    (["juice", "fruit juice"], ["20", "21", "22"], "Juice must be Ch20-22"),
    (["soap", "detergent"], ["33", "34"], "Soap must be Ch33/34"),
]


def main() -> None:
    rows = _read_xlsx_rows(Path("data/correct_datas.xlsx"))
    columns = list(rows[0].keys()) if rows else []
    print("Columns:", columns)
    print("Total rows:", len(rows))
    print("Sample:")
    for row in rows[:10]:
        print(row)

    issues: list[str] = []
    for index, row in enumerate(rows, 2):
        values = list(row.values())
        desc = str(values[0]).strip() if len(values) > 0 else ""
        hsn_raw = str(values[1]).strip() if len(values) > 1 else ""
        digits = re.sub(r"[^0-9]", "", hsn_raw)

        if not desc or desc.lower() == "nan":
            issues.append(f"Row {index}: Empty description")
        if not digits:
            issues.append(f"Row {index}: Empty HSN for '{desc}'")
        if digits and len(digits) not in (2, 4, 6, 8):
            issues.append(f"Row {index}: Odd-length HSN '{hsn_raw}' for '{desc}'")

        if digits:
            chapter = digits[:2]
            desc_lower = desc.lower()
            for keywords, valid_chapters, message in CHAPTER_CHECKS:
                if any(keyword in desc_lower for keyword in keywords) and chapter not in valid_chapters:
                    issues.append(
                        f"Row {index}: WRONG CHAPTER — {message}, got Ch{chapter} for '{desc[:60]}'"
                    )

    print(f"\nTotal issues: {len(issues)}")
    for issue in issues[:100]:
        print(issue)


if __name__ == "__main__":
    main()
