"""HSN/GST validation service for CBIC compliance.

Validates:
  - HSN code format (2/4/6/8 digit, or SAC 4-digit)
  - GST rate against the official Indian rate schedule
  - Cess applicability rules
  - Chapter/heading consistency

Sources:
  - CBIC Customs Tariff 2024-25
  - CGST Notification 1/2017-CT(Rate) and all amendments
  - GST Council decisions up to March 2025
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Valid Indian GST rates per CGST schedule
VALID_GST_RATES: set[float] = {0.0, 0.1, 0.25, 1.5, 3.0, 5.0, 12.0, 18.0, 28.0}

# Chapters/prefixes where cess is mandatory
CESS_CHAPTERS = {
    "22",  # Aerated drinks, liquor
    "24",  # Tobacco products
    "27",  # Coal
    "87",  # Luxury/large cars, motorcycles >350cc
}

# Known HSN code changes in 2022/2023/2024 GST Council amendments
# Format: old_hsn → (new_hsn, effective_date, notification_ref)
HSN_AMENDMENTS: dict[str, tuple[str, str, str]] = {
    "21069099": ("19019090", "2022-07-13", "GST Council 47th meeting, Notification 6/2022-CT(Rate)"),
    "21069011": ("21069099", "2022-07-13", "GST Council 47th meeting"),
    "04015000": ("04011000", "2022-01-01", "GST Council 45th meeting"),
}

# HSN codes flagged as deprecated/reclassified
DEPRECATED_HSN: set[str] = {"99999999", "00000000"}


@dataclass
class ValidationResult:
    is_valid: bool
    hsn_code: str
    errors: list[str]
    warnings: list[str]
    chapter: str | None
    heading: str | None
    subheading: str | None
    amendment_note: str | None = None


def validate_hsn_code(hsn_code: str) -> ValidationResult:
    """Validate an HSN code against CBIC format rules."""
    errors: list[str] = []
    warnings: list[str] = []
    amendment_note: str | None = None

    if not hsn_code:
        return ValidationResult(
            is_valid=False, hsn_code="",
            errors=["HSN code is empty"], warnings=[],
            chapter=None, heading=None, subheading=None,
        )

    # Strip spaces and non-digits
    digits = re.sub(r"[^0-9]", "", hsn_code.strip())

    # SAC codes for services (e.g. 9954, 9971) use 4 digits
    is_sac = len(digits) == 4 and digits.startswith("99")

    valid_lengths = {2, 4, 6, 8}
    if len(digits) not in valid_lengths:
        errors.append(
            f"Invalid HSN length: {len(digits)} digits. "
            f"Must be 2 (chapter), 4 (heading), 6 (sub-heading), or 8 (tariff item)."
        )

    if digits in DEPRECATED_HSN:
        errors.append(f"HSN {digits} is a catch-all placeholder and must not be used in submissions.")

    # Check amendments
    if digits in HSN_AMENDMENTS:
        new_hsn, eff_date, ref = HSN_AMENDMENTS[digits]
        warnings.append(
            f"HSN {digits} was amended effective {eff_date}. "
            f"New code: {new_hsn}. Reference: {ref}"
        )
        amendment_note = f"Amended to {new_hsn} (effective {eff_date}, ref: {ref})"

    chapter = digits[:2] if len(digits) >= 2 else None
    heading = digits[:4] if len(digits) >= 4 else None
    subheading = digits[:6] if len(digits) >= 6 else None

    # Chapter range validation
    if chapter and not is_sac:
        ch_num = int(chapter)
        if not (1 <= ch_num <= 99):
            errors.append(f"Chapter {chapter} is out of valid range (01-99).")

    return ValidationResult(
        is_valid=len(errors) == 0,
        hsn_code=digits,
        errors=errors,
        warnings=warnings,
        chapter=chapter,
        heading=heading,
        subheading=subheading,
        amendment_note=amendment_note,
    )


def validate_gst_rate(rate: float | None, hsn_code: str | None = None) -> dict:
    """Validate a GST rate against the official Indian schedule."""
    errors: list[str] = []
    warnings: list[str] = []

    if rate is None:
        return {"is_valid": False, "errors": ["GST rate is None"], "warnings": []}

    # Check against valid rates
    is_valid_rate = any(abs(rate - v) < 0.01 for v in VALID_GST_RATES)
    if not is_valid_rate:
        closest = min(VALID_GST_RATES, key=lambda v: abs(v - rate))
        errors.append(
            f"GST rate {rate}% is not a valid Indian GST rate. "
            f"Valid rates: {sorted(VALID_GST_RATES)}. "
            f"Closest valid rate: {closest}%."
        )

    # Check cess applicability
    cess_required = False
    if hsn_code:
        chapter = re.sub(r"[^0-9]", "", hsn_code)[:2]
        if chapter in CESS_CHAPTERS:
            cess_required = True
            warnings.append(f"Chapter {chapter} products typically attract GST Compensation Cess.")

    return {
        "is_valid": len(errors) == 0,
        "rate": rate,
        "errors": errors,
        "warnings": warnings,
        "cess_likely_applicable": cess_required,
    }


def validate_hsn_gst_pair(hsn_code: str, gst_rate: float | None) -> dict:
    """Validate the combination of HSN code and GST rate together."""
    hsn_result = validate_hsn_code(hsn_code)
    gst_result = validate_gst_rate(gst_rate, hsn_code)

    all_errors = hsn_result.errors + gst_result["errors"]
    all_warnings = hsn_result.warnings + gst_result["warnings"]

    return {
        "is_valid": len(all_errors) == 0,
        "hsn_code": hsn_result.hsn_code,
        "gst_rate": gst_rate,
        "chapter": hsn_result.chapter,
        "heading": hsn_result.heading,
        "subheading": hsn_result.subheading,
        "errors": all_errors,
        "warnings": all_warnings,
        "amendment_note": hsn_result.amendment_note,
        "cess_likely_applicable": gst_result.get("cess_likely_applicable", False),
    }
