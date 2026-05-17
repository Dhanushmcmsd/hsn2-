#!/usr/bin/env python3
"""Build data/kerala_invoice_benchmark.xlsx — Malayalam/Kerala retail invoice lines."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "kerala_invoice_benchmark.xlsx"
CORPUS = ROOT / "data" / "kerala_retail_aliases.json"

# Invoice-style lines (roman OCR, brands, qty) — Kerala retail bills
INVOICE_LINES = [
    "EASTERN MANJAL PODI 100G",
    "NIRAPARA PUTTU PODI 500G",
    "DOUBLE HORSE APPAM PODI 1KG",
    "VELICHENNA 1L",
    "VELICHENNA 500ML",
    "PUZHUKKALARI 1KG",
    "MATTA ARI 5KG",
    "NADAN ARI 2KG",
    "THUVARA PARIPPU 500G",
    "CHERUPAYAR 500G",
    "UZHUNNU WHITE REGULAR 500G",
    "KADALA 1KG",
    "MANJALPODI 100G",
    "MULAKUPODI 200G",
    "SAMBARPODI 100G",
    "RASAMPODI 50G",
    "PUTTUPODI 1KG",
    "IDLYAPPAMPODI 500G",
    "KADALA MAVU 500G",
    "VELLACHENNA 1L",
    "NENDRAN CHIPS 200G",
    "SHARKARA UPPERI 150G",
    "KODAMPULI 100G",
    "PULI INJI 200G",
    "INJI PULI 250G",
    "MANGA ACHAR 400G",
    "CHEMMEEN ACHAR 200G",
    "KARIMEEN FRESH 1KG",
    "AYALA FRESH 500G",
    "MATHI FRESH 1KG",
    "CHEMMEEN 500G",
    "VELICHENNA POUCH 1L",
    "PALAT SAMBAR MASALA 100GM",
    "REAL1 PUTTU PODI 1Kg",
    "LEMAM CHIRATTA PUTTU",
    "SARVODAYA KASTHURI MANJAL 70g",
    "CHAKKA GREEN JACKFRUIT POWDER 200g",
    "AJMI STEAM MADE PUTTUPODI 1KG",
    "AVAL WHITE REGULAR 500G",
    "CB MATTA BROKEN RICE NICE 500G",
    "OM SHANTHI PUJA OIL 1000ml",
    "BRAHMINS FRIED RAVA 1KG",
    "KITCHEN TREASURE CHILLI POWDER 100G",
    "REAL1 KOZHUVA ROAST 100G",
    "TRIPTI NADAN UNNIYAPPAM 180G",
    "PAVITHRAM TAMARIND 100G",
    "BODHINI APPAM IDIAPPAM PODI 1KG",
    "MILMA GHEE BTL 50ml",
    "TN KERALA INST.SADHYA PALADA MIX 200g",
    "CAMLIN SMALL SC MR NOTE BOOK 80P",
    "VKC FTGR DB19109 MAR.BG.LAD 04",
]

# Malayalam script bill lines from corpus (high-signal)
SCRIPT_LINES = [
    "വെളിച്ചെണ്ണ 1 ലീറ്റർ",
    "മഞ്ഞൾപൊടി 100 ഗ്രാം",
    "ചായപ്പൊടി 200 ഗ്രാം",
    "തുവര പരിപ്പ് 500 ഗ്രാം",
    "പുട്ട് പൊടി 1 കിലോ",
    "മട്ട അരി 5 കിലോ",
    "കടല മാവ് 500 ഗ്രാം",
    "നേന്ദ്രൻ ചിപ്സ് 200 ഗ്രാം",
    "കരിമീൻ 1 കിലോ",
    "കൊടംപുളി 100 ഗ്രാം",
]


def main() -> int:
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("pip install openpyxl")

    lines = list(INVOICE_LINES)
    # Add roman phrases from corpus (non-ambiguous, with HSN)
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    seen = {x.upper() for x in lines}
    for row in corpus:
        if row.get("language_code") != "ml-roman":
            continue
        if int(row.get("priority", 100)) < 50:
            continue
        term = (row.get("original_term") or "").strip()
        if not term or " " not in term:
            continue
        inv = f"{term} 500G"
        if inv.upper() not in seen:
            lines.append(inv)
            seen.add(inv.upper())
        if len(lines) >= 85:
            break

    lines.extend(SCRIPT_LINES)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "products"
    ws.append(["description"])
    for line in lines:
        ws.append([line])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"Wrote {len(lines)} invoice lines to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
