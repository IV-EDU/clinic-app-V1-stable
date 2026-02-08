from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import re
import zipfile
import csv
from xml.etree import ElementTree as ET

from datetime import date, timedelta


XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


@dataclass
class PaymentRecord:
    """Single payment row parsed from the legacy Excel."""

    short_id: str
    full_name: str
    phone: str
    total_cents: int
    paid_cents: int
    remaining_cents: int
    raw_remaining: str
    notes: str
    page_number: str = ""
    treatment_type: str = ""
    visit_label: str = ""
    paid_at: str = ""
    exam_flag: int = 0
    follow_flag: int = 0
    method: str = ""
    discount_cents: int = 0
    doctor_label: str = ""
    payment_id: str = ""

    @property
    def total_fmt(self) -> str:
        return f"{self.total_cents / 100:.2f}" if self.total_cents else ""

    @property
    def paid_fmt(self) -> str:
        return f"{self.paid_cents / 100:.2f}" if self.paid_cents else ""

    @property
    def remaining_fmt(self) -> str:
        return f"{self.remaining_cents / 100:.2f}" if self.remaining_cents else ""


@dataclass
class PatientPreview:
    """Aggregated view of a patient with all their payments."""

    base_short_id: str
    full_name: str
    phone: str
    payments: List[PaymentRecord]
    total_cents: int = 0
    paid_cents: int = 0
    remaining_cents: int = 0

    @property
    def display_short_id(self) -> str:
        return self.base_short_id

    @property
    def total_fmt(self) -> str:
        return f"{self.total_cents / 100:.2f}" if self.total_cents else ""

    @property
    def paid_fmt(self) -> str:
        return f"{self.paid_cents / 100:.2f}" if self.paid_cents else ""

    @property
    def remaining_fmt(self) -> str:
        return f"{self.remaining_cents / 100:.2f}" if self.remaining_cents else ""


def normalize_file_number(raw: Optional[str]) -> str:
    """Return a normalised file number used for grouping.

    Rules:
      * Ignore any non‑digit characters.
      * Treat leading zeros as the same number (001 -> 1).
      * Empty / no digits -> "" (no usable file number).
    """
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        return ""
    normalized = digits.lstrip("0")
    return normalized or "0"


def normalize_name(raw: Optional[str]) -> str:
    """Normalise a patient name for grouping comparisons."""
    if not raw:
        return ""
    # Collapse whitespace and lower-case for safer comparison
    collapsed = " ".join(str(raw).split())
    return collapsed.strip().lower()


def first_two_name_tokens(norm_name: str) -> str:
    """Return 'first name + second name' from a normalised name string."""
    if not norm_name:
        return ""
    parts = [p for p in norm_name.split(" ") if p]
    return " ".join(parts[:2])


def build_patient_group_key(short_id: str, full_name: str, phone: str = "") -> str:
    """Build a stable key for 'this should be one patient' grouping.

    We follow the rules discussed for the import:
      * For file numbers, ignore text and use only digits (with leading zeros
        removed) so '001', '1', or 'P-001' all line up.
      * For names, we primarily compare the first + second name (two tokens)
        so minor differences at the end do not split a patient.
      * If no usable file number exists, fall back to phone, then full name.
    """
    norm_file = normalize_file_number(short_id)
    norm_name = normalize_name(full_name)
    first_two = first_two_name_tokens(norm_name)

    if norm_file and first_two:
        return f"{norm_file}|{first_two}"
    if norm_file and norm_name:
        return f"{norm_file}|{norm_name}"
    phone_clean = (phone or "").strip()
    if phone_clean:
        return f"phone|{phone_clean}"
    if norm_name:
        return f"name|{norm_name}"
    return ""


def _first_page_number(raw: Optional[str]) -> str:
    """Return the first notebook page number found in a raw page string.

    Examples:
      "45-46" -> "45"
      "0012" -> "12"
      "12 , 14" -> "12"
    """
    if not raw:
        return ""
    txt = str(raw).strip()
    if not txt:
        return ""
    # Normalize Arabic-Indic digits.
    txt = txt.translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
            }
        )
    )
    m = re.search(r"(\d+)", txt)
    if not m:
        return ""
    digits = (m.group(1) or "").lstrip("0")
    return digits or "0"


def build_patient_group_key_strict(page_raw: str, full_name: str, phone: str = "") -> str:
    """Build a *strict* grouping key for the legacy Excel preview.

    We avoid aggressive merging by not using "first two names" matching here.
    Instead we prefer:
      - first page number + exact normalized full name (and phone when present),
      - otherwise phone,
      - otherwise exact normalized full name.
    """
    page0 = _first_page_number(page_raw)
    name_norm = normalize_name(full_name)
    phone_norm = normalize_phone(phone)

    if page0 and name_norm and phone_norm:
        return f"pg|{page0}|{name_norm}|{phone_norm}"
    if page0 and name_norm:
        return f"pg|{page0}|{name_norm}"
    if phone_norm:
        return f"phone|{phone_norm}"
    if name_norm:
        return f"name|{name_norm}"
    return ""


def normalize_phone(raw: Optional[str]) -> str:
    """Return a phone string with only digits, used for duplicate checks."""
    if not raw:
        return ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits


def _parse_date_from_text(raw: str) -> str:
    """Best-effort parse of a date from a cell or notes string.

    Returns an ISO date string (YYYY-MM-DD) or "" if parsing fails.
    """
    txt = (raw or "").strip()
    if not txt:
        return ""

    lower_txt = txt.lower()

    # Normalize Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) to ASCII digits, because some
    # clinics use Arabic Excel locales.
    txt = txt.translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
                "٫": ".",
                "،": ",",
            }
        )
    )

    # Safety: if the cell looks like a date range (from/to), do not guess.
    # We intentionally keep this conservative and return blank.
    # Examples:
    #  - "17/09/2023-23/03/2023"
    #  - "10/09/23 - 24/09/23"
    #  - "2023-09-17 إلى 2023-10-01"
    range_markers = ("الى", "إلى", " to ", "–", "—")

    # Safety rule: if the cell contains more than one date (ranges like
    # "17/09/2023-23/03/2023"), do not guess. Leave it blank.
    date_like = re.findall(
        r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}"
        r"|\d{1,2}[/-]\d{1,2}[/-]\d{4}"
        r"|\d{1,2}[/-]\d{1,2}[/-]\d{2}(?!\d)"
        r"|\d{1,2}\.\d{1,2}\.\d{4})",
        txt,
    )
    if len(date_like) >= 2:
        return ""

    if len(date_like) == 1:
        if any(m in lower_txt for m in range_markers):
            return ""
        # Hyphen-range where the second date is partial/unparseable (e.g. "17/09/2023-23/03").
        if re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*[-–—]\s*\d", txt):
            return ""
        # Partial date range "dd/mm - dd/mm"
        if re.search(r"\d{1,2}[/-]\d{1,2}\s*[-–—]\s*\d{1,2}[/-]\d{1,2}", txt):
            return ""

    # Excel serial number (typical range for recent years).
    # It may come as "45678" or "45678.0".
    m = re.fullmatch(r"(\d+)(?:[.,]\d+)?", txt)
    if m:
        try:
            n = int(float(txt.replace(",", ".")))
            if 30000 <= n <= 60000:
                base = date(1899, 12, 30)
                return (base + timedelta(days=n)).isoformat()
        except ValueError:
            pass

    # yyyy-mm-dd with optional time
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", txt)
    if m:
        y, m1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, m1, d1).isoformat()
        except ValueError:
            return ""

    # yyyy/mm/dd or yyyy-mm-dd
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", txt)
    if m:
        y, m1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, m1, d1).isoformat()
        except ValueError:
            return ""

    # dd/mm/yyyy or dd-mm-yyyy
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", txt)
    if m:
        d1, m1, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, m1, d1).isoformat()
        except ValueError:
            return ""

    # dd/mm/yy (common in some sheets, including date ranges like 10/09/23-24/09/23)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2})(?!\d)", txt)
    if m:
        d1, m1, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = 2000 + y2 if y2 < 70 else 1900 + y2
        try:
            return date(y, m1, d1).isoformat()
        except ValueError:
            return ""

    # dd.mm.yyyy
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", txt)
    if m:
        d1, m1, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, m1, d1).isoformat()
        except ValueError:
            return ""

    return ""


def _load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    """Return the shared strings table from the workbook, if present."""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    data = zf.read("xl/sharedStrings.xml")
    root = ET.fromstring(data)
    shared: List[str] = []
    for si in root.findall(f"{XLSX_NS}si"):
        parts: List[str] = []
        for t in si.findall(f".//{XLSX_NS}t"):
            if t.text:
                parts.append(t.text)
        shared.append("".join(parts).strip())
    return shared


def _iter_sheet_rows(
    zf: zipfile.ZipFile, shared: List[str], sheet_path: str
) -> List[List[str]]:
    """Return raw cell values (as strings) for all rows in the given sheet."""
    if sheet_path not in zf.namelist():
        raise FileNotFoundError(sheet_path)
    data = zf.read(sheet_path)
    root = ET.fromstring(data)
    rows: List[List[str]] = []
    sheet_data = root.find(f"{XLSX_NS}sheetData")
    if sheet_data is None:
        return rows
    for row in sheet_data.findall(f"{XLSX_NS}row"):
        values: List[str] = []
        for cell in row.findall(f"{XLSX_NS}c"):
            cell_type = cell.get("t")
            v_el = cell.find(f"{XLSX_NS}v")
            if v_el is None or v_el.text is None:
                values.append("")
                continue
            text = v_el.text
            if cell_type == "s":
                try:
                    idx = int(text)
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(shared):
                    text = shared[idx]
            values.append(str(text).strip())
        rows.append(values)
    return rows


def _parse_money(value: str) -> int:
    """Parse a money-like string into integer cents."""
    value = (value or "").replace(",", "").strip()
    if not value:
        return 0
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return 0


def _normalize_visit_type(value: str) -> str:
    """Normalize a visit type string to 'exam' or 'followup'."""
    raw = (value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if "exam" in lowered or "diagnos" in lowered or "كشف" in raw:
        return "exam"
    if "follow" in lowered or "متاب" in raw:
        return "followup"
    return ""


def _iter_sheet_rows_by_col(
    zf: zipfile.ZipFile, shared: List[str], sheet_path: str
) -> List[Dict[str, str]]:
    """Return rows as {column_letter: value} dicts for the given sheet.

    This is more robust than positional lists when some cells are empty,
    because we use the cell reference (e.g. \"A2\") to determine the column.
    """
    data = zf.read(sheet_path)
    root = ET.fromstring(data)
    sheet_data = root.find(f"{XLSX_NS}sheetData")
    if sheet_data is None:
        return []

    def decode(cell) -> str:
        cell_type = cell.get("t")
        v_el = cell.find(f"{XLSX_NS}v")
        if v_el is None or v_el.text is None:
            return ""
        text = v_el.text
        if cell_type == "s":
            try:
                idx = int(text)
            except (TypeError, ValueError):
                return ""
            if 0 <= idx < len(shared):
                return shared[idx].strip()
            return ""
        return str(text).strip()

    rows: List[Dict[str, str]] = []
    for row in sheet_data.findall(f"{XLSX_NS}row"):
        row_vals: Dict[str, str] = {}
        for cell in row.findall(f"{XLSX_NS}c"):
            ref = cell.get("r") or ""
            col_letters = "".join(ch for ch in ref if ch.isalpha())
            if not col_letters:
                continue
            row_vals[col_letters] = decode(cell)
        rows.append(row_vals)
    return rows


def _find_sheet_path_by_name(zf: zipfile.ZipFile, target_name: str) -> Optional[str]:
    """Best-effort lookup of a worksheet path by the human sheet name.

    We inspect xl/workbook.xml and map the visual order of <sheet> elements to
    sheet1.xml, sheet2.xml, ... which matches how Excel usually stores them.
    If anything goes wrong we return None and the caller can fall back.
    """
    try:
        data = zf.read("xl/workbook.xml")
    except KeyError:
        return None
    root = ET.fromstring(data)
    sheets_el = root.find(f"{XLSX_NS}sheets")
    if sheets_el is None:
        return None
    idx = 0
    target_name_norm = (target_name or "").strip().lower()
    for sheet in sheets_el.findall(f"{XLSX_NS}sheet"):
        idx += 1
        name = (sheet.get("name") or "").strip().lower()
        if name == target_name_norm:
            path = f"xl/worksheets/sheet{idx}.xml"
            if path in zf.namelist():
                return path
    return None


def _preview_key_first_stable(p: PaymentRecord, mode: str) -> str:
    """Return a grouping key for legacy Excel preview by mode."""
    mode = (mode or "safe").strip().lower()
    if mode == "aggressive":
        # Most merging: page number only (fallback to name).
        page0 = _first_page_number(p.short_id)
        if page0:
            return f"pg|{page0}"
        name_norm = normalize_name(p.full_name)
        return f"name|{name_norm}" if name_norm else ""
    if mode == "normal":
        page0 = _first_page_number(p.short_id)
        name_norm = normalize_name(p.full_name)
        if page0 and name_norm:
            return f"pg|{page0}|{name_norm}"
        phone_norm = normalize_phone(p.phone)
        if phone_norm:
            return f"phone|{phone_norm}"
        if name_norm:
            return f"name|{name_norm}"
        return ""
    # safe (default)
    # safe (default) uses the legacy notebook page number (stored in short_id)
    return build_patient_group_key_strict(p.short_id, p.full_name, p.phone)


def _preview_key_csv(p: PaymentRecord, mode: str) -> str:
    """Return a grouping key for CSV/template preview by mode."""
    mode = (mode or "safe").strip().lower()
    file_norm = normalize_file_number(p.short_id)
    name_norm = normalize_name(p.full_name)
    phone_norm = normalize_phone(p.phone)

    if mode == "aggressive":
        # Most merging: file number only, fallback to name.
        if file_norm:
            return f"file|{file_norm}"
        return f"name|{name_norm}" if name_norm else ""
    if mode == "normal":
        if file_norm and name_norm:
            return f"file|{file_norm}|{name_norm}"
        if phone_norm:
            return f"phone|{phone_norm}"
        if name_norm:
            return f"name|{name_norm}"
        return ""
    # safe (default)
    if file_norm and name_norm and phone_norm:
        return f"file|{file_norm}|{name_norm}|{phone_norm}"
    if file_norm and name_norm:
        return f"file|{file_norm}|{name_norm}"
    if phone_norm:
        return f"phone|{phone_norm}"
    if name_norm:
        return f"name|{name_norm}"
    return ""


def analyze_first_stable_excel(path: Path, max_preview_rows: int = 200, mode: str = "safe") -> Dict[str, Any]:
    """Read the legacy 'First stable' Excel file and return a safe preview.

    This does **not** write to the database. It only inspects the file and
    returns aggregate counts + a small table of example rows that can be shown
    in the Admin → Data import tab.
    """
    payments, counts = extract_first_stable_payments(path)
    if not payments:
        return {"counts": counts, "rows": []}

    # Group by patient so the preview feels like patient files with their payments.
    patients: Dict[str, PatientPreview] = {}
    auto_index = 1
    pages_by_key: Dict[str, str] = {}

    for p in payments:
        # Group with explicit mode so preview counts match the chosen import mode.
        key = _preview_key_first_stable(p, mode)
        if not key:
            continue
        if p.short_id and key not in pages_by_key:
            pages_by_key[key] = p.short_id
        if key not in patients:
            patients[key] = PatientPreview(
                # Display should match the app's file number format (e.g. P000123),
                # while grouping can still normalize digits via build_patient_group_key().
                base_short_id=(p.short_id or "").strip(),
                full_name=p.full_name,
                phone=p.phone,
                payments=[],
            )
        grp = patients[key]
        if not grp.phone and p.phone:
            grp.phone = p.phone
        grp.payments.append(p)
        grp.total_cents += p.total_cents
        grp.paid_cents += p.paid_cents
        grp.remaining_cents += p.remaining_cents

    for grp in patients.values():
        if not grp.base_short_id:
            grp.base_short_id = f"AUTO-{auto_index:03d}"
            auto_index += 1

    # Make the summary counts match the selected preview mode.
    counts = dict(counts or {})
    counts["patients"] = len(patients)

    rows_payload: List[Dict[str, Any]] = []
    for key, grp in sorted(patients.items(), key=lambda it: ((it[1].base_short_id or ""), it[1].full_name))[
        :max_preview_rows
    ]:
        payments_payload: List[Dict[str, Any]] = []
        for p in grp.payments:
            status = "done" if p.remaining_cents == 0 else "owing"
            if p.exam_flag:
                visit_type = "exam"
            elif p.follow_flag:
                visit_type = "followup"
            else:
                visit_type = _normalize_visit_type(p.visit_label)
            payments_payload.append(
                {
                    "total_fmt": p.total_fmt,
                    "paid_fmt": p.paid_fmt,
                    "remaining_fmt": p.remaining_fmt,
                    "raw_remaining": p.raw_remaining,
                    "notes": p.notes,
                    "status": status,
                    "treatment_type": p.treatment_type,
                    "visit_label": p.visit_label,
                    "visit_type": visit_type,
                    "paid_at": p.paid_at,
                }
            )

        primary_page = pages_by_key.get(key, "")

        rows_payload.append(
            {
                # Legacy Excel uses notebook/page numbers, not the app's file numbers.
                # Keep file number empty in the preview, and show the notebook number
                # in the page-number chip instead.
                "short_id": "",
                "primary_page_number": primary_page,
                "full_name": grp.full_name,
                "phone": grp.phone,
                "total_fmt": grp.total_fmt,
                "paid_fmt": grp.paid_fmt,
                "remaining_fmt": grp.remaining_fmt,
                "payments_count": len(grp.payments),
                "payments": payments_payload,
            }
        )

    # Duplicate suggestions can still be helpful, but keep the *preview* grouping strict.
    duplicates_safe = build_duplicate_suggestions(payments, aggressive=False)
    duplicates_aggressive = build_duplicate_suggestions(payments, aggressive=True)

    return {
        "counts": counts,
        "rows": rows_payload,
        "duplicates": duplicates_safe,
        "duplicates_aggressive": duplicates_aggressive,
    }


def analyze_import_csv_template(path: Path, max_preview_rows: int = 200, mode: str = "safe") -> Dict[str, Any]:
    """Read a clinic-import CSV template and return a safe preview payload.

    This is intended for other clinics that do not have the legacy Excel file.
    It does **not** write to the database.
    """
    payments, counts = extract_import_csv_payments(path)

    if not payments:
        return {"counts": counts, "rows": []}

    # Group by patient for preview cards.
    patients: Dict[str, PatientPreview] = {}
    auto_index = 1
    pages_by_key: Dict[str, str] = {}

    for p in payments:
        key = _preview_key_csv(p, mode)
        if not key:
            continue
        if p.page_number and key not in pages_by_key:
            pages_by_key[key] = p.page_number
        if key not in patients:
            patients[key] = PatientPreview(
                # Display should match the app's file number format (e.g. P000123),
                # while grouping can still normalize digits via build_patient_group_key().
                base_short_id=(p.short_id or "").strip(),
                full_name=p.full_name,
                phone=p.phone,
                payments=[],
            )
        grp = patients[key]
        if not grp.phone and p.phone:
            grp.phone = p.phone
        grp.payments.append(p)
        grp.total_cents += p.total_cents
        grp.paid_cents += p.paid_cents
        grp.remaining_cents += p.remaining_cents

    for grp in patients.values():
        if not grp.base_short_id:
            grp.base_short_id = f"AUTO-{auto_index:03d}"
            auto_index += 1

    # Make the summary counts match the selected preview mode.
    counts = dict(counts or {})
    counts["patients"] = len(patients)

    rows_payload: List[Dict[str, Any]] = []
    for group_key, grp in sorted(
        patients.items(), key=lambda item: (item[1].base_short_id or "", item[1].full_name)
    )[:max_preview_rows]:
        payments_payload: List[Dict[str, Any]] = []
        for p in grp.payments:
            status = "done" if p.remaining_cents == 0 else "owing"
            visit_type = _normalize_visit_type(p.visit_label)
            payments_payload.append(
                {
                    "total_fmt": p.total_fmt,
                    "paid_fmt": p.paid_fmt,
                    "remaining_fmt": p.remaining_fmt,
                    "raw_remaining": p.raw_remaining,
                    "notes": p.notes,
                    "status": status,
                    "treatment_type": p.treatment_type,
                    "visit_label": p.visit_label,
                    "visit_type": visit_type,
                    "paid_at": p.paid_at,
                }
            )

        # Best-effort primary page number (optional column in template).
        primary_page = pages_by_key.get(group_key, "")

        rows_payload.append(
            {
                "short_id": grp.display_short_id,
                "primary_page_number": primary_page,
                "full_name": grp.full_name,
                "phone": grp.phone,
                "total_fmt": grp.total_fmt,
                "paid_fmt": grp.paid_fmt,
                "remaining_fmt": grp.remaining_fmt,
                "payments_count": len(grp.payments),
                "payments": payments_payload,
            }
        )

    # Duplicate suggestions reuse the same logic.
    duplicates_safe = build_duplicate_suggestions(payments, aggressive=False)
    duplicates_aggressive = build_duplicate_suggestions(payments, aggressive=True)

    return {
        "counts": counts,
        "rows": rows_payload,
        "duplicates": duplicates_safe,
        "duplicates_aggressive": duplicates_aggressive,
    }


def extract_import_csv_payments(path: Path) -> Tuple[List[PaymentRecord], Dict[str, Any]]:
    """Parse a clinic-import CSV (template or export) into payment records + counts.

    This is used for:
      * the Admin → Data import preview (no DB writes), and
      * the real import step (DB writes) once enabled.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    payments: List[PaymentRecord] = []
    total_rows = 0
    patients_ids: set[str] = set()
    money_payments = 0
    zero_entries = 0
    skipped_rows = 0
    missing_file = 0
    missing_name = 0

    def get_first(row: dict[str, Any], keys: list[str]) -> str:
        for k in keys:
            if k in row and row.get(k) is not None:
                return str(row.get(k) or "").strip()
        return ""

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = row or {}

            row_has_any = any(str(v or "").strip() for v in row.values())
            if not row_has_any:
                continue
            total_rows += 1

            short_id = get_first(row, ["file_number", "patient_short_id", "patient_file_number", "file"])
            page_number = get_first(row, ["page_number", "page_numbers"])
            name = get_first(row, ["full_name", "patient_name", "name"])
            phone = get_first(row, ["phone", "patient_phone"])
            date_raw = get_first(row, ["date", "paid_at"])
            notes = get_first(row, ["notes", "note"])
            visit_type = get_first(row, ["visit_type", "visit"])
            treatment_type = get_first(row, ["treatment_type", "treatment"])
            total_raw = get_first(row, ["total_amount", "total"])
            paid_raw = get_first(row, ["paid_today", "paid"])
            remaining_raw = get_first(row, ["remaining", "remaining_amount"])
            method = get_first(row, ["method", "payment_method"])
            discount_raw = get_first(row, ["discount", "discount_amount"])
            doctor_label = get_first(row, ["doctor_label", "doctor"])
            payment_id = get_first(row, ["payment_id", "id"])

            total_cents = _parse_money(total_raw)
            paid_cents = _parse_money(paid_raw)
            remaining_cents = _parse_money(remaining_raw)
            if remaining_raw.strip() == "خالص":
                remaining_cents = 0
            discount_cents = _parse_money(discount_raw)

            paid_at_iso = _parse_date_from_text(date_raw) if date_raw else ""

            norm_visit = _normalize_visit_type(visit_type)
            exam_flag = 1 if norm_visit == "exam" else 0
            follow_flag = 1 if norm_visit == "followup" else 0

            has_amounts = bool(total_cents or paid_cents or remaining_cents)
            has_details = bool(
                (date_raw or "").strip()
                or (notes or "").strip()
                or (visit_type or "").strip()
                or (treatment_type or "").strip()
                or (remaining_raw or "").strip()
                or (method or "").strip()
                or (discount_raw or "").strip()
                or (doctor_label or "").strip()
                or (payment_id or "").strip()
            )
            has_patient_info = bool(
                (short_id or "").strip()
                or (page_number or "").strip()
                or (name or "").strip()
                or (phone or "").strip()
            )

            # Skip formatting-only / empty-info rows.
            if (not has_amounts) and (not has_details):
                skipped_rows += 1
                continue
            if not has_patient_info:
                skipped_rows += 1
                continue

            if not short_id:
                missing_file += 1
            if not name:
                missing_name += 1

            group_key = build_patient_group_key(short_id, name, phone)
            if group_key:
                patients_ids.add(group_key)

            if has_amounts:
                money_payments += 1
            else:
                zero_entries += 1

            payments.append(
                PaymentRecord(
                    short_id=short_id,
                    full_name=name,
                    phone=phone,
                    total_cents=total_cents,
                    paid_cents=paid_cents,
                    remaining_cents=remaining_cents,
                    raw_remaining=remaining_raw,
                    notes=notes,
                    page_number=page_number,
                    treatment_type=treatment_type,
                    visit_label=visit_type,
                    paid_at=paid_at_iso,
                    exam_flag=exam_flag,
                    follow_flag=follow_flag,
                    method=method,
                    discount_cents=discount_cents,
                    doctor_label=doctor_label,
                    payment_id=payment_id,
                )
            )

    counts: Dict[str, Any] = {
        "total_rows": total_rows,
        "patients": len(patients_ids),
        "payments": money_payments,
        "zero_entries": zero_entries,
        "skipped_rows": skipped_rows,
        "missing_file": missing_file,
        "missing_name": missing_name,
    }
    return payments, counts


def extract_first_stable_payments(path: Path) -> Tuple[List[PaymentRecord], Dict[str, Any]]:
    """Parse the legacy Excel and return raw payment rows + summary counts.

    This helper is shared by:
      * the Admin → Data import preview (via analyze_first_stable_excel), and
      * the CLI preview-import command that loads a temporary database.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    payments: List[PaymentRecord] = []
    total_rows = 0
    patients_ids: set[str] = set()
    money_payments = 0
    zero_entries = 0
    skipped_rows = 0
    missing_file = 0
    missing_name = 0

    with zipfile.ZipFile(path, "r") as zf:
        shared = _load_shared_strings(zf)
        # Find the explicit "patient records" sheet; if missing, we do not guess.
        sheet_path = _find_sheet_path_by_name(zf, "patient records")
        if not sheet_path:
            counts = {
                "total_rows": 0,
                "patients": 0,
                "payments": 0,
                "missing_file": 0,
                "missing_name": 0,
            }
            return [], counts

        raw_rows = _iter_sheet_rows_by_col(zf, shared, sheet_path)
        if not raw_rows or len(raw_rows) < 2:
            counts = {
                "total_rows": 0,
                "patients": 0,
                "payments": 0,
                "missing_file": 0,
                "missing_name": 0,
            }
            return [], counts

        # Header row tells us which column is which. We use the Arabic labels
        # instead of hard-coded indices so we do not mis-wire fields.
        header_row = raw_rows[0]

        def find_col(predicates: List[str]) -> Optional[str]:
            for col, text in header_row.items():
                t = (text or "").replace(" ", "")
                if all(p in t for p in predicates):
                    return col
            return None

        file_col = find_col(["رقم", "دفتر"]) or find_col(["رقم", "ملف"])
        name_col = find_col(["الاسم"])
        phone_col = find_col(["رقم", "تلفون"]) or find_col(["رقم", "تليفون"])
        exam_col = find_col(["كشف"])
        follow_col = find_col(["متابع"])
        treatment_col = find_col(["نوع", "العلاج"])
        total_col = find_col(["اجمالي", "المبلغ"]) or find_col(["إجمالي", "المبلغ"])
        paid_col = find_col(["دفعه"]) or find_col(["دفعة"])
        remaining_col = find_col(["المبلغ", "المتبقي"])
        notes_col = find_col(["ملاحظات"])
        # Prefer the "today + time" date column when present, else any "تاريخ".
        date_col = find_col(["تاريخ", "اليوم", "توقيت"]) or find_col(["تاريخ"])  # optional explicit date column

        data_rows = raw_rows[1:]

        def cell(row_vals: Dict[str, str], col: Optional[str]) -> str:
            if not col:
                return ""
            return (row_vals.get(col) or "").strip()

        for row_vals in data_rows:
            if not any(row_vals.values()):
                continue

            short_id = cell(row_vals, file_col)
            name = cell(row_vals, name_col)
            phone = cell(row_vals, phone_col)

            total_raw = cell(row_vals, total_col)
            paid_raw = cell(row_vals, paid_col)
            remaining_raw = cell(row_vals, remaining_col)
            notes = cell(row_vals, notes_col)
            date_raw = cell(row_vals, date_col)

            # Visit type from كشف / متابعه
            visit_label = ""
            exam_val = cell(row_vals, exam_col)
            follow_val = cell(row_vals, follow_col)
            if exam_val:
                visit_label = exam_val
            elif follow_val:
                visit_label = follow_val

            # Flags based on whether the checkbox/cell is ticked or contains text.
            exam_flag = 1 if exam_val else 0
            follow_flag = 1 if follow_val else 0

            # Also look at the text itself for keywords in case the sheet stores
            # 'كشف' / 'متابعة' directly in the cell.
            if not exam_flag and exam_val:
                if "كشف" in exam_val:
                    exam_flag = 1
            if not follow_flag and follow_val:
                if "متاب" in follow_val:
                    follow_flag = 1

            treatment_type = cell(row_vals, treatment_col)

            row_has_any_relevant = bool(
                short_id
                or name
                or phone
                or total_raw
                or paid_raw
                or remaining_raw
                or notes
                or date_raw
                or exam_val
                or follow_val
                or treatment_type
            )
            if not row_has_any_relevant:
                continue
            total_rows += 1

            remaining_clean = (remaining_raw or "").strip()
            if remaining_clean == "خالص":
                remaining_cents = 0
            else:
                remaining_cents = _parse_money(remaining_raw)

            total_cents = _parse_money(total_raw)
            paid_cents = _parse_money(paid_raw)

            # Try to capture the original payment date from either the explicit
            # date column only. We do not guess dates from notes, because notes
            # can contain unrelated numbers that look like dates.
            paid_at_iso = ""
            if date_raw:
                paid_at_iso = _parse_date_from_text(date_raw)

            has_amounts = bool(total_cents or paid_cents or remaining_cents)
            has_details = bool(
                (notes or "").strip()
                or (treatment_type or "").strip()
                or (visit_label or "").strip()
                or (date_raw or "").strip()
                or (paid_at_iso or "").strip()
                or (remaining_raw or "").strip()
                or exam_flag
                or follow_flag
            )

            # If there is only a bare name without a file number and without
            # any payment information, skip creating a patient for it.
            if (not short_id) and name and not (has_amounts or has_details):
                skipped_rows += 1
                continue
            if (not has_amounts) and (not has_details):
                skipped_rows += 1
                continue

            if not short_id:
                missing_file += 1
            if not name:
                missing_name += 1

            # Track distinct patients using the same grouping rules as the preview.
            group_key = build_patient_group_key(short_id, name, phone)
            if group_key:
                patients_ids.add(group_key)

            if has_amounts:
                money_payments += 1
            else:
                zero_entries += 1

            payments.append(
                PaymentRecord(
                    short_id=short_id,
                    full_name=name,
                    phone=phone,
                    total_cents=total_cents,
                    paid_cents=paid_cents,
                    remaining_cents=remaining_cents,
                    raw_remaining=remaining_raw,
                    notes=notes,
                    treatment_type=treatment_type,
                    visit_label=visit_label,
                    paid_at=paid_at_iso,
                    exam_flag=exam_flag,
                    follow_flag=follow_flag,
                )
            )

    counts: Dict[str, Any] = {
        "total_rows": total_rows,
        "patients": len(patients_ids),
        "payments": money_payments,
        "zero_entries": zero_entries,
        "skipped_rows": skipped_rows,
        "missing_file": missing_file,
        "missing_name": missing_name,
    }
    return payments, counts


def build_duplicate_suggestions(
    payments: List[PaymentRecord], aggressive: bool = False
) -> List[Dict[str, Any]]:
    """Build a lightweight list of possible duplicate patients.

    When aggressive=False (default, Option B):
      - Same first + second name (normalised), and
      - Either the phone numbers match, or at least one phone is missing.

    When aggressive=True (Option A):
      - Same first + second name only (phone is ignored).
    """
    groups: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}

    for p in payments:
        norm_name = normalize_name(p.full_name)
        first_two = first_two_name_tokens(norm_name)
        if not first_two:
            continue

        phone_norm = normalize_phone(p.phone)
        file_norm = normalize_file_number(p.short_id)
        key = first_two
        subkey = (file_norm, phone_norm)

        g = groups.setdefault(key, {})
        cand = g.get(subkey)
        if not cand:
            cand = {
                "sample_name": p.full_name or first_two,
                "short_id": file_norm,
                "raw_file": p.short_id or "",
                "phone": p.phone or "",
                "phone_norm": phone_norm,
                "payments_count": 0,
                "total_cents": 0,
                "paid_cents": 0,
                "remaining_cents": 0,
            }
            g[subkey] = cand
        cand["payments_count"] += 1
        cand["total_cents"] += p.total_cents
        cand["paid_cents"] += p.paid_cents
        cand["remaining_cents"] += p.remaining_cents

    suggestions: List[Dict[str, Any]] = []
    for first_two, cand_map in groups.items():
        cand_list = list(cand_map.values())
        if len(cand_list) < 2:
            continue

        # Decide if this group should be suggested under the chosen mode.
        if aggressive:
            # Option A – any name group with 2+ candidates.
            if len(cand_list) < 2:
                continue
        else:
            # Option B – same name AND phones match or missing for at least one.
            phone_counts: Dict[str, int] = {}
            missing_phone = False
            for c in cand_list:
                ph = c["phone_norm"]
                if not ph:
                    missing_phone = True
                else:
                    phone_counts[ph] = phone_counts.get(ph, 0) + 1
            duplicates_same_phone = any(count >= 2 for count in phone_counts.values())

            if not ((duplicates_same_phone or missing_phone) and len(cand_list) >= 2):
                continue

        # Shape payload for the UI (no heavy logic here).
        candidates_payload: List[Dict[str, Any]] = []
        for c in cand_list:
            total_cents = c["total_cents"]
            remaining_cents = c["remaining_cents"]
            candidates_payload.append(
                {
                    "short_id": c["short_id"],
                    "raw_file": c["raw_file"],
                    "phone": c["phone"],
                    "payments_count": c["payments_count"],
                    "total_fmt": f"{total_cents / 100:.2f}" if total_cents else "",
                    "remaining_fmt": f"{remaining_cents / 100:.2f}" if remaining_cents else "",
                }
            )

        suggestions.append(
            {
                "first_two_name": first_two,
                "display_name": cand_list[0]["sample_name"],
                "candidates": candidates_payload,
            }
        )

    return suggestions
