import json
import os
import re


CHAPTER_PRODUCT_MAP = {
    "64": ["footwear", "shoe", "sandal", "slipper", "chappal", "vkc"],
    "33": ["cosmetic", "shampoo", "toothpaste", "perfume", "soap", "cream", "agarbatti"],
    "34": ["detergent", "cleaner", "phenyl", "harpic", "dishwash"],
    "19": ["biscuit", "cookie", "wafer", "bread", "cake", "snack", "chips"],
    "10": ["rice", "basmati", "matta", "wheat", "oats"],
    "11": ["flour", "atta", "maida", "suji", "rava"],
    "04": ["milk", "ghee", "butter", "cheese", "paneer", "yogurt", "curd"],
    "09": ["spice", "masala", "turmeric", "chilli", "pepper", "cardamom"],
    "15": ["oil", "sesame", "sunflower", "palm oil", "coconut oil"],
    "22": ["juice", "aerated", "water", "soda", "drink", "beverage"],
    "17": ["sugar", "jaggery", "candy"],
    "18": ["chocolate", "cocoa"],
    "20": ["jam", "pickle", "sauce", "ketchup", "preserve"],
}


def main() -> None:
    batch_dir = "data/product_batches"
    if not os.path.exists(batch_dir):
        print("No batch directory found")
        return

    all_issues: list[str] = []
    total_rows = 0

    for fname in sorted(os.listdir(batch_dir)):
        if not fname.endswith(".json") or fname.startswith("_"):
            continue
        fpath = os.path.join(batch_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            all_issues.append(f"{fname}: JSON parse error — {exc}")
            continue

        for index, item in enumerate(data):
            desc = str(item.get("Description", "")).strip()
            hsn_raw = str(item.get("HSN_Ref", "")).strip()
            digits = re.sub(r"[^0-9]", "", hsn_raw)
            total_rows += 1

            if not desc:
                all_issues.append(f"{fname}[{index}]: Empty description")
                continue
            if not digits:
                all_issues.append(f"{fname}[{index}]: Empty HSN for '{desc[:50]}'")
                continue

            chapter = digits[:2]
            desc_lower = desc.lower()

            for expected_chapter, keywords in CHAPTER_PRODUCT_MAP.items():
                if any(keyword in desc_lower for keyword in keywords):
                    if chapter != expected_chapter and not (
                        chapter in ["20", "21", "22"] and expected_chapter in ["20", "21", "22"]
                    ):
                        all_issues.append(
                            f"{fname}[{index}]: CHAPTER MISMATCH — '{desc[:50]}' "
                            f"expected Ch{expected_chapter}, got Ch{chapter} (HSN {hsn_raw})"
                        )
                    break

    print(f"Scanned {total_rows} batch rows, found {len(all_issues)} issues")
    for issue in all_issues[:100]:
        print(issue)


if __name__ == "__main__":
    main()
