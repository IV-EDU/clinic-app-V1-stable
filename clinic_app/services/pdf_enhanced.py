"""Enhanced PDF utilities built on top of fpdf2 for bilingual receipts with Arabic support."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
import base64

# QR Code imports - with fallback for missing library
try:
    import qrcode
    QR_CODE_AVAILABLE = True
except ImportError:
    QR_CODE_AVAILABLE = False

from fpdf import FPDF, XPos, YPos
from flask import current_app
from clinic_app.services.theme_settings import get_setting

# Optional Arabic shaping dependencies (graceful fallback)
try:
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore
    _AR_SHAPING_AVAILABLE = True
except Exception:
    _AR_SHAPING_AVAILABLE = False


class ReceiptPDF(FPDF):
    """Enhanced helper around FPDF to render bilingual (EN/AR) receipts with proper Arabic support."""

    def __init__(self, font_path: str | None, locale: str = "en") -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self._font_path = font_path
        self._locale = locale
        self._family = "Helvetica"
        self._rtl_mode = False  # RTL text mode
        self._ensure_fonts()
        self.add_page()

    def _ensure_fonts(self) -> None:
        # Build candidate list (prefer app-provided path, then DejaVu)
        candidates: list[Path] = []

        # Provided path (absolute or relative)
        if self._font_path:
            p = Path(self._font_path)
            if not p.is_absolute():
                try:
                    from flask import current_app

                    root = Path(getattr(current_app, "root_path", "."))
                    p = root.joinpath(self._font_path)
                except Exception:
                    p = Path(self._font_path)
            candidates.append(p)

        # Project fonts
        candidates.append(Path("static/fonts/DejaVuSans.ttf"))

        def _load_font(path: Path) -> bool:
            try:
                family = "Cairo" if "cairo" in path.name.lower() else ("DejaVu" if "dejavu" in path.name.lower() else "Custom")
                self.add_font(family, "", str(path), uni=True)
                self.add_font(family, "B", str(path), uni=True)
                self._family = family
                self.set_font(self._family, "B", 18)
                return True
            except Exception as e:
                print(f"Font loading failed for {path}: {e}")
                return False

        loaded = False
        for cand in candidates:
            if cand.exists() and _load_font(cand):
                loaded = True
                break

        if not loaded:
            self._family = "Helvetica"
            self.set_font(self._family, "B", 18)

    def set_rtl_mode(self, enabled: bool) -> None:
        """Enable or disable RTL (right-to-left) mode for Arabic text."""
        self._rtl_mode = enabled
        # If the underlying fpdf2 supports set_rtl, enable it for better spacing
        try:
            self.set_rtl(enabled)  # type: ignore[attr-defined]
        except Exception:
            pass
        if enabled:
            # Swap margins for RTL layout
            self.set_left_margin(self.r_margin)
            self.set_right_margin(self.l_margin)
        else:
            # Reset margins for LTR layout
            self.set_left_margin(25)
            self.set_right_margin(25)

    def _normalize_arabic_text(self, text: str) -> str:
        """Normalize Arabic text for proper rendering."""
        if not self._rtl_mode or not self._is_arabic_text(text):
            return text
        
        # Remove zero-width spaces and other formatting characters
        text = text.replace('\u200B', '')  # Zero width space
        text = text.replace('\u200C', '')  # Zero width non-joiner
        text = text.replace('\u200D', '')  # Zero width joiner
        
        # Normalize Arabic letters (replace presentation forms with normalized forms)
        arabic_normalization = {
            '\uFB50': '\u0671',  # Arabic Letter Alef Wasla -> Alef
            '\uFB51': '\u0671',  # Arabic Letter Alef Wasla -> Alef
        }
        
        for old, new in arabic_normalization.items():
            text = text.replace(old, new)
        
        return text

    def _is_arabic_text(self, text: str) -> bool:
        """Check if text contains Arabic characters."""
        arabic_chars = [c for c in text if 0x0600 <= ord(c) <= 0x06FF]
        return len(arabic_chars) > 0

    def _reorder_rtl_text(self, text: str) -> str:
        """Apply proper RTL text reordering for mixed content."""
        if not self._rtl_mode:
            return text
        
        # For pure Arabic text, use proper Arabic text processing
        if self._is_arabic_text(text) and not re.search(r'[a-zA-Z]', text):
            # Don't reverse Arabic text - it's already in the correct order
            # Just ensure proper Arabic character processing
            return self._process_arabic_text_order(text)
        
        # For mixed content (Arabic + English), handle special cases
        if self._is_arabic_text(text) and re.search(r'[a-zA-Z]', text):
            return self._process_mixed_rtl_text(text)
        
        # For pure English text in RTL mode
        if not self._is_arabic_text(text):
            # Keep English text in LTR order even in RTL mode
            return text
        
        return text

    def _shape_if_arabic(self, text: str) -> str:
        """Shape and reorder Arabic text if shaping libs are available, else fallback."""
        if not self._rtl_mode or not self._is_arabic_text(text):
            return text
        if _AR_SHAPING_AVAILABLE:
            try:
                reshaped = arabic_reshaper.reshape(text)
                # Wrap with RTL markers to encourage correct direction
                return "\u202B" + get_display(reshaped) + "\u202C"
            except Exception:
                pass
        # Fallback to normalization + basic reordering
        text = self._normalize_arabic_text(text)
        return self._reorder_rtl_text(text)
    
    def _process_arabic_text_order(self, text: str) -> str:
        """Process Arabic text for proper RTL display."""
        # Arabic text should not be reversed - it's already in correct order
        # This method ensures proper character processing
        return text
    
    def _process_mixed_rtl_text(self, text: str) -> str:
        """Handle mixed Arabic-English text in RTL mode."""
        # Split text into Arabic and English parts
        # For simplicity, return as-is with proper spacing
        # A more sophisticated implementation would use bidirectional text algorithms
        arabic_parts = re.split(r'([a-zA-Z]+)', text)
        
        # Process each part
        processed_parts = []
        for part in arabic_parts:
            if re.match(r'^[a-zA-Z]+$', part):
                # English part - keep as is (LTR)
                processed_parts.append(part)
            else:
                # Arabic part - keep as is (RTL)
                processed_parts.append(part)
        
        return ''.join(processed_parts)

    def heading(self, text_key: str, locale: str = "en") -> None:
        """Render heading with proper language support."""
        from clinic_app.services.i18n import translate_text
        
        # Get localized text for the heading
        if locale == "ar":
            # For Arabic, use translation with proper formatting
            heading_text = translate_text("ar", f"receipt_{text_key}")
            # If translation not found, fallback to the key itself
            if heading_text == f"receipt_{text_key}":
                heading_text = text_key
        else:
            # For English, use the text_key directly
            heading_text = text_key
            
        self.set_font(self._family, "B", 18)
        
        if self._rtl_mode:
            ar_txt = self._shape_if_arabic(heading_text)
            self.cell(0, 10, ar_txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
        else:
            self.cell(0, 10, heading_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
        self.set_font_size(14)
        self.ln(4)

    def kv_block(self, rows: Iterable[tuple[str, str]], locale: str = "en") -> None:
        """Render key-value pairs in two clean columns (invoice style)."""
        from clinic_app.services.i18n import translate_text

        self.set_font(self._family, "", 11)
        width = max(0.1, self.w - self.l_margin - self.r_margin)
        label_w = width * 0.45
        value_w = width - label_w
        line_height = 7

        for idx, (label, value) in enumerate(rows):
            # Localize the label if needed
            if label.startswith("key:"):
                key = label[4:]
                localized = translate_text("ar" if locale == "ar" else "en", key)
                localized_label = localized if localized != key else key
            else:
                localized_label = label

            label_text = f"{localized_label}:"
            value_text = str(value)

            if locale == "ar":
                # Build a single RTL line to avoid word breaks
                combined = f"{value_text} : {self._shape_if_arabic(localized_label)}"
                self.set_xy(self.l_margin, self.y)
                self.multi_cell(width, line_height, combined, border=0, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            else:
                if self._is_arabic_text(label_text):
                    label_text = self._shape_if_arabic(label_text)
                if self._is_arabic_text(value_text):
                    value_text = self._shape_if_arabic(value_text)
                self.set_xy(self.l_margin, self.y)
                self.cell(label_w, line_height, label_text, align="L")
                self.cell(value_w, line_height, value_text, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

            # Light separator
            if idx < len(rows) - 1:
                self.set_draw_color(230, 230, 230)
                self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)

        self.ln(3)

    def note(self, text: str) -> None:
        """Render note text with Arabic support."""
        self.set_font(self._family, "", 11)
        
        # Shape/normalize Arabic text
        shaped = self._shape_if_arabic(text) if self._rtl_mode else text
        self.multi_cell(0, 6, shaped, border=0, new_x=XPos.LMARGIN, align="R" if self._rtl_mode else "L")
        self.ln(2)

    def table_header(self, headers: list[str]) -> None:
        """Render professional table headers with Arabic support."""
        self.set_font(self._family, "B", 11)
        self.set_fill_color(41, 128, 185)  # Professional blue
        self.set_text_color(255, 255, 255)  # White text
        
        cell_width = (self.w - self.l_margin - self.r_margin) / len(headers)
        
        for header in headers:
            # Shape/normalize Arabic headers
            header_txt = self._shape_if_arabic(header)
            self.cell(cell_width, 10, header_txt, border=1, fill=True, new_x=XPos.LMARGIN, align="C")
        self.ln()
        self.set_font(self._family, "", 10)
        self.set_text_color(0, 0, 0)  # Reset to black

    def table_row(self, cells: list[str], fill: bool = False) -> None:
        """Render professional table row with Arabic support."""
        cell_width = (self.w - self.l_margin - self.r_margin) / len(cells)
        bg_color = (248, 249, 250) if fill else (255, 255, 255)
        self.set_fill_color(*bg_color)
        
        for cell in cells:
            # Shape/normalize Arabic cells
            cell_txt = self._shape_if_arabic(cell)
            self.cell(cell_width, 8, cell_txt, border=1, fill=fill, new_x=XPos.LMARGIN, align="C")
        self.ln()

    def clinic_header(self, clinic_name: str, clinic_address: str = "", phone: str = "") -> None:
        """Render enhanced clinic header information with Arabic support."""
        # Add decorative line at top
        self.set_line_width(0.5)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)
        self.ln(3)
        
        self.set_font(self._family, "B", 16)
        
        # Shape/Normalize Arabic clinic name
        normalized_name = self._shape_if_arabic(clinic_name)
        
        if self._rtl_mode:
            self.cell(0, 12, normalized_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        else:
            self.cell(0, 12, normalized_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        
        self.set_font(self._family, "", 11)
        
        if clinic_address:
            normalized_address = self._shape_if_arabic(clinic_address)
            self.cell(0, 7, normalized_address, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        
        if phone:
            from clinic_app.services.i18n import translate_text
            phone_label = translate_text("ar", "phone") if self._rtl_mode else "Phone"
            phone_text = f"{phone_label}: {phone}"
            self.cell(0, 7, phone_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
        
        # Add decorative line below header
        self.ln(2)
        self.set_line_width(0.5)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.y, self.w - self.r_margin, self.y)
        self.ln(6)

    def render(self) -> bytes:
        """Render the PDF and return as bytes (robust)."""
        try:
            data = self.output()
            return data if isinstance(data, (bytes, bytearray)) else bytes(data)
        except Exception:
            output = self.output()
            return output if isinstance(output, (bytes, bytearray)) else bytes(output, "latin1")

    def add_qr_code(self, data: str, x: float, y: float, size: float = 15) -> None:
        """Add QR code to PDF with proper fallback handling."""
        
        if not QR_CODE_AVAILABLE:
            # Fallback: draw QR code placeholder with data
            self.set_line_width(1)
            self.set_draw_color(41, 128, 185)
            self.rect(x, y, size, size)
            
            self.set_font(self._family, "", 6)
            self.set_xy(x + 1, y + 1)
            qr_text = f"QR Code\n{data[:20]}{'...' if len(data) > 20 else ''}"
            self.multi_cell(size - 2, 3, qr_text, border=0, align="C")
            return

        try:
            # Generate QR matrix and draw directly to avoid Pillow dependency.
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=4,
                border=1,
            )
            qr.add_data(data)
            qr.make(fit=True)

            matrix = qr.get_matrix()
            if not matrix:
                raise ValueError("QR matrix generation returned empty data.")

            modules = len(matrix)
            module_size = size / modules if modules else size

            self.set_fill_color(255, 255, 255)
            self.rect(x, y, size, size, "F")
            self.set_draw_color(0, 0, 0)
            self.set_fill_color(0, 0, 0)
            self.set_line_width(0)

            for row_idx, row in enumerate(matrix):
                for col_idx, value in enumerate(row):
                    if value:
                        self.rect(
                            x + col_idx * module_size,
                            y + row_idx * module_size,
                            module_size,
                            module_size,
                            "F",
                        )
        except Exception as e:
            # Fallback if QR code generation fails
            print(f"QR code generation failed: {e}")
            self._add_qr_code_placeholder(x, y, size, "QR ERROR")

    def _add_qr_code_placeholder(self, x: float, y: float, size: float, text: str = "QR Code") -> None:
        """Add QR code placeholder with border and text."""
        self.set_line_width(1)
        self.set_draw_color(41, 128, 185)
        self.rect(x, y, size, size)
        
        # Add QR pattern simulation
        self.set_draw_color(41, 128, 185)
        self.set_line_width(0.5)
        
        # Draw corner squares (typical QR pattern)
        self.rect(x + 2, y + 2, 4, 4, 'F')
        self.rect(x + size - 6, y + 2, 4, 4, 'F')
        self.rect(x + 2, y + size - 6, 4, 4, 'F')
        
        # Draw center pattern
        self.rect(x + size/2 - 2, y + size/2 - 2, 4, 4, 'F')
        
        # Add text
        self.set_font(self._family, "", 6)
        self.set_xy(x + 1, y + size + 2)
        self.cell(size - 2, 3, text, align="C")


def generate_expense_receipt_pdf(expense_receipt: dict, materials: list[dict], supplier: dict, settings: dict) -> bytes:
    """Generate professional PDF for expense receipts with Arabic support."""
    # Determine locale and font path from config
    locale = settings.get("locale", "en")
    try:
        cfg = current_app.config  # type: ignore[attr-defined]
    except Exception:
        cfg = {}
    cairo_default = "static/fonts/Cairo-Regular.ttf"
    dejavu_default = "static/fonts/DejaVuSans.ttf"

    currency_label = cfg.get("CURRENCY_LABEL", "EGP")

    if locale == "ar":
        ar_pref = (cfg.get("PDF_DEFAULT_ARABIC", "cairo") or "cairo").lower()
        ar_path = cfg.get("PDF_FONT_PATH_AR") if ar_pref == 'cairo' else cfg.get("PDF_FONT_PATH")
        font_path = ar_path or cairo_default
        if not Path(font_path).exists():
            font_path = dejavu_default
    else:
        font_path = cfg.get("PDF_FONT_PATH", dejavu_default)
    pdf = ReceiptPDF(font_path=font_path, locale=locale)
    
    # Check if Arabic is requested
    if locale == "ar":
        pdf.set_rtl_mode(True)
    
    # Header
    pdf.clinic_header(
        settings.get("clinic_name", "Dental Clinic"),
        settings.get("clinic_address", ""),
        settings.get("clinic_phone", "")
    )
    
    pdf.heading("Expense Receipt", "فاتورة مصروفات")
    
    # Receipt information
    pdf.kv_block([
        ("Receipt Number", expense_receipt.get("serial_number", "")),
        ("Date", expense_receipt.get("receipt_date", "")),
        ("Supplier", supplier.get("name", "")),
        ("Contact Person", supplier.get("contact_person", "")),
        ("Phone", supplier.get("phone", "")),
        ("Email", supplier.get("email", "")),
    ])
    
    # Items table
    pdf.ln(4)
    pdf.set_font(pdf._family, "B", 12)
    pdf.cell(0, 8, "Items:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    
    # Table headers
    pdf.table_header(["Material", "Quantity", "Unit Price", "Total Price", "Notes"])
    
    # Table rows
    subtotal = 0
    for i, item in enumerate(materials):
        pdf.table_row([
            item.get("material_name", ""),
            f"{item.get('quantity', 0):.2f}",
            f"{item.get('unit_price', 0)/100:.2f} EGP",
            f"{item.get('total_price', 0)/100:.2f} EGP",
            item.get("notes", "")[:30] + "..." if len(item.get("notes", "")) > 30 else item.get("notes", "")
        ], fill=(i % 2 == 0))
        
        subtotal += item.get('total_price', 0)
    
    # Totals section
    pdf.ln(4)
    tax_amount = expense_receipt.get("tax_amount", 0)
    total_amount = expense_receipt.get("total_amount", 0)
    
    pdf.set_font(pdf._family, "B", 12)
    pdf.cell(0, 8, "Financial Summary:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(pdf._family, "", 11)
    
    pdf.kv_block([
        ("Subtotal", f"{subtotal/100:.2f} EGP"),
        ("Tax Amount", f"{tax_amount/100:.2f} EGP"),
        ("Total Amount", f"{total_amount/100:.2f} EGP"),
    ])
    
    # Notes section
    if expense_receipt.get("notes"):
        pdf.ln(4)
        pdf.set_font(pdf._family, "B", 12)
        pdf.cell(0, 8, "Notes:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.note(expense_receipt["notes"])
    
    # Footer
    pdf.ln(8)
    pdf.set_font(pdf._family, "", 9)
    pdf.cell(0, 6, f"Generated on: {expense_receipt.get('created_at', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    
    return pdf.render()


def generate_payment_receipt_pdf(payment: dict, patient: dict, treatment_details: dict, format_type: str, locale: str = "en", print_options: dict | None = None) -> bytes:
    """Generate enhanced patient receipt PDFs with multiple format options and Arabic support."""
    
    if print_options is None:
        print_options = {}
    
    # Default print options
    include_qr = print_options.get("include_qr", True)
    include_notes = print_options.get("include_notes", True)
    include_treatment = print_options.get("include_treatment", True)
    add_watermark = print_options.get("watermark", False)
    
    # Choose font path based on locale and config
    try:
        cfg = current_app.config  # type: ignore[attr-defined]
    except Exception:
        cfg = {}
    currency_label = cfg.get("CURRENCY_LABEL", "EGP")

    # Force a known-good Unicode font (DejaVu) resolved from app root
    dejavu_default = Path("static/fonts/DejaVuSans.ttf")
    font_path = dejavu_default
    try:
        from flask import current_app

        root = Path(getattr(current_app, "root_path", "."))
        cand = root.joinpath("static", "fonts", "DejaVuSans.ttf")
        if cand.exists():
            font_path = cand
    except Exception:
        pass

    pdf = ReceiptPDF(font_path=str(font_path), locale=locale)
    
    # Ensure correct text direction and margins per locale
    if locale == "ar":
        pdf.set_rtl_mode(True)
    else:
        pdf.set_rtl_mode(False)
    
    def _pdf_logo_path() -> str | None:
        """Resolve the best available logo path for PDFs.

        Order of preference:
        1) Explicit PDF logo from settings.
        2) Auto-detected pdf-logo-current.* under data/theme/.
        3) Existing header logo from settings.
        4) Auto-detected header logo under data/theme/.
        """
        try:
            root = Path(getattr(current_app, "config", {}).get("DATA_ROOT", "data"))

            def _existing(path: Path) -> str | None:
                return str(path) if path.exists() else None

            rel_pdf = get_setting("pdf_logo_path")
            if rel_pdf:
                # Handle absolute paths or Windows-style separators safely
                cand = Path(rel_pdf)
                if cand.is_absolute() and _existing(cand):
                    return str(cand)
                rel_norm = Path(rel_pdf.replace("\\", "/"))
                hit = _existing(root / rel_norm)
                if hit:
                    return hit

            # Auto-detect a current PDF logo if the setting is empty/stale
            for cand in root.glob("theme/pdf-logo-current.*"):
                hit = _existing(cand)
                if hit:
                    return hit

            rel_header = get_setting("logo_path")
            if rel_header:
                cand = Path(rel_header)
                if cand.is_absolute() and _existing(cand):
                    return str(cand)
                rel_norm = Path(rel_header.replace("\\", "/"))
                hit = _existing(root / rel_norm)
                if hit:
                    return hit

            for cand in root.glob("theme/logo-current.*"):
                hit = _existing(cand)
                if hit:
                    return hit
        except Exception:
            return None
        return None

    logo_path = _pdf_logo_path()
    logo_used = False
    if logo_path:
        try:
            pdf.set_y(pdf.t_margin)
            # Center a generous stamp-like logo; clamp width to printable area
            printable_w = pdf.w - pdf.l_margin - pdf.r_margin
            target_w = min(printable_w, 120)
            pdf.set_x((pdf.w - target_w) / 2)
            pdf.image(logo_path, w=target_w)
            pdf.ln(8)
            logo_used = True
        except Exception:
            pass
    
    # Add watermark if requested (light, centered, after page creation)
    if add_watermark:
        _add_watermark(pdf, "CLINIC COPY", locale)

    from clinic_app.services.i18n import translate_text

    def fallback_text(en_text: str, ar_text: str) -> str:
        return ar_text if locale == "ar" else en_text

    def translate_label(key: str, fallback: str) -> str:
        text = translate_text(locale, key)
        return text if text != key else fallback

    def shape_text(value: str | None) -> str:
        if value is None:
            value = ""
        return pdf._shape_if_arabic(str(value)) if pdf._rtl_mode else str(value)

    def format_currency(amount_cents: int | None) -> str:
        amount = (amount_cents or 0) / 100
        return f"{amount:.2f} {currency_label}"

    def render_header(meta_rows: list[tuple[str, str]], logo_shown: bool) -> None:
        clinic_name = treatment_details.get("clinic_name") or "Clinic App"
        clinic_address = treatment_details.get("clinic_address", "")
        clinic_phone = treatment_details.get("clinic_phone", "")
        total_width = pdf.w - pdf.l_margin - pdf.r_margin
        gap = 6
        left_width = total_width * 0.55
        right_width = total_width - left_width - gap
        if right_width < 60:
            right_width = 60
            left_width = total_width - right_width - gap
        start_y = pdf.y
        if pdf._rtl_mode:
            clinic_x = pdf.w - pdf.r_margin - left_width
            meta_x = pdf.l_margin
        else:
            clinic_x = pdf.l_margin
            meta_x = pdf.l_margin + left_width + gap
        align = "R" if pdf._rtl_mode else "L"
        pdf.set_xy(clinic_x, start_y)
        pdf.set_font(pdf._family, "B", 15)
        if not logo_shown:
            pdf.cell(left_width, 8, shape_text(clinic_name), border=0, align=align)
            cursor_y = start_y + 8
        else:
            cursor_y = start_y
        pdf.set_font(pdf._family, "", 10)
        if clinic_address:
            pdf.set_xy(clinic_x, cursor_y)
            pdf.multi_cell(left_width, 5.5, shape_text(clinic_address), border=0, align=align)
            cursor_y = pdf.y
        if clinic_phone:
            pdf.set_xy(clinic_x, cursor_y)
            pdf.multi_cell(left_width, 5.5, shape_text(clinic_phone), border=0, align=align)
            cursor_y = pdf.y
        clinic_bottom = cursor_y
        label_height = 4
        value_height = 6
        padding = 3
        meta_height = padding * 2 + len(meta_rows) * (label_height + value_height + 2)
        pdf.set_fill_color(249, 250, 253)
        pdf.set_draw_color(220, 223, 230)
        pdf.rect(meta_x, start_y, right_width, meta_height, style="DF")
        meta_cursor = start_y + padding
        for label, value in meta_rows:
            pdf.set_xy(meta_x + padding, meta_cursor)
            pdf.set_font(pdf._family, "", 8)
            pdf.cell(right_width - 2 * padding, label_height, shape_text(label), align=align)
            meta_cursor += label_height + 0.8
            pdf.set_xy(meta_x + padding, meta_cursor)
            pdf.set_font(pdf._family, "B", 11)
            pdf.cell(right_width - 2 * padding, value_height, shape_text(value or "—"), align=align)
            meta_cursor += value_height + 1.8
        pdf.set_draw_color(0, 0, 0)
        meta_bottom = start_y + meta_height
        pdf.set_y(max(clinic_bottom, meta_bottom) + 6)

    def draw_info_block(x: float, width: float, title: str, rows: list[tuple[str, str]], top_y: float) -> float:
        saved_y = pdf.y
        align = "R" if pdf._rtl_mode else "L"
        header_height = 8
        pdf.set_fill_color(245, 247, 252)
        pdf.rect(x, top_y, width, header_height, style="F")
        pdf.set_xy(x + 3, top_y + 2)
        pdf.set_font(pdf._family, "B", 11)
        pdf.cell(width - 6, 4, shape_text(title), align=align)
        block_cursor = top_y + header_height + 2
        for label, value in rows:
            pdf.set_xy(x + 3, block_cursor)
            pdf.set_font(pdf._family, "", 8.5)
            pdf.multi_cell(width - 6, 4, shape_text(label), border=0, align=align)
            block_cursor = pdf.y + 0.8
            pdf.set_xy(x + 3, block_cursor)
            pdf.set_font(pdf._family, "B", 11)
            val_text = value if value not in (None, "") else "—"
            pdf.multi_cell(width - 6, 6, shape_text(val_text), border=0, align=align)
            block_cursor = pdf.y + 2
        block_height = max(header_height + 4, block_cursor - top_y)
        pdf.set_draw_color(224, 227, 234)
        pdf.rect(x, top_y, width, block_height)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_y(saved_y)
        return top_y + block_height

    def render_info_blocks(
        left_title: str,
        left_rows: list[tuple[str, str]],
        right_title: str | None = None,
        right_rows: list[tuple[str, str]] | None = None,
    ) -> None:
        total_width = pdf.w - pdf.l_margin - pdf.r_margin
        gap = 6
        start_y = pdf.y
        if right_rows:
            left_width = total_width * 0.5
            right_width = total_width - left_width - gap
            if pdf._rtl_mode:
                left_x = pdf.l_margin + right_width + gap
                right_x = pdf.l_margin
            else:
                left_x = pdf.l_margin
                right_x = pdf.l_margin + left_width + gap
            left_bottom = draw_info_block(left_x, left_width, left_title, left_rows, start_y)
            right_bottom = draw_info_block(right_x, right_width, right_title or "", right_rows, start_y)
            pdf.set_y(max(left_bottom, right_bottom) + 6)
        else:
            bottom = draw_info_block(pdf.l_margin, total_width, left_title, left_rows, start_y)
            pdf.set_y(bottom + 6)

    def render_text_panel(title: str, text: str) -> None:
        if not text:
            return
        align = "R" if pdf._rtl_mode else "L"
        pdf.ln(2)
        pdf.set_font(pdf._family, "B", 11)
        pdf.cell(0, 6, shape_text(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align=align)
        pdf.set_font(pdf._family, "", 10)
        pdf.set_fill_color(249, 250, 252)
        pdf.set_draw_color(224, 227, 234)
        pdf.multi_cell(0, 6, shape_text(text), border=1, align=align, fill=True)
        pdf.ln(1)

    receipt_number = payment.get("id", "")[-8:].upper() if payment.get("id") else "N/A"
    receipt_date = payment.get("paid_at", "") or ""
    method_value = (payment.get("method") or "cash").lower()
    method_label = translate_label(f"method_{method_value}", (payment.get("method") or "cash").title())
    patient_rows = [
        (translate_label("name", fallback_text("Name", "الاسم")), patient.get("full_name") or "—"),
        (translate_label("file_no", fallback_text("File No.", "رقم الملف")), patient.get("short_id") or "—"),
        (translate_label("phone", fallback_text("Phone", "الهاتف")), patient.get("phone") or "—"),
    ]
    payment_rows = [
        (translate_label("summary_total", fallback_text("Total", "الإجمالي")), format_currency(payment.get("total_amount_cents"))),
        (translate_label("summary_discount", fallback_text("Discount", "الخصم")), format_currency(payment.get("discount_cents"))),
        (translate_label("summary_paid", fallback_text("Paid", "المدفوع")), format_currency(payment.get("amount_cents"))),
        (translate_label("summary_remaining", fallback_text("Remaining", "المتبقي")), format_currency(payment.get("remaining_cents"))),
    ]
    meta_rows = [
        (translate_label("receipt_number_label", fallback_text("Receipt No.", "رقم الإيصال")), receipt_number),
        (translate_label("receipt_date_label", fallback_text("Date", "التاريخ")), receipt_date),
        (translate_label("payment_method", fallback_text("Payment Method", "طريقة الدفع")), method_label),
    ]

    patient_block_title = translate_label("receipt_patient_label", fallback_text("Patient", "المريض"))
    payments_block_title = translate_label("payments", fallback_text("Payments", "المدفوعات"))

    if format_type == "full":
        render_header(meta_rows, logo_used)
        render_info_blocks(patient_block_title, patient_rows, payments_block_title, payment_rows)
        if include_treatment and payment.get("treatment"):
            render_text_panel(translate_label("treatment", fallback_text("Treatment", "العلاج")), payment["treatment"])
        if include_notes and payment.get("note"):
            render_text_panel(translate_label("sheet_notes", fallback_text("Notes", "ملاحظات")), payment["note"])

    elif format_type == "summary":
        render_header(meta_rows, logo_used)
        summary_rows = [
            (translate_label("receipt_date_label", fallback_text("Date", "التاريخ")), receipt_date or "—"),
            (translate_label("summary_paid", fallback_text("Paid", "المدفوع")), format_currency(payment.get("amount_cents"))),
            (translate_label("payment_method", fallback_text("Payment Method", "طريقة الدفع")), method_label),
        ]
        render_info_blocks(patient_block_title, patient_rows, payments_block_title, summary_rows)
        if include_treatment and payment.get("treatment"):
            render_text_panel(translate_label("treatment", fallback_text("Treatment", "العلاج")), payment["treatment"])
        if include_notes and payment.get("note"):
            render_text_panel(translate_label("sheet_notes", fallback_text("Notes", "ملاحظات")), payment["note"])

    elif format_type == "treatment":
        render_header(meta_rows, logo_used)
        treatment_rows = [
            (translate_label("treatment_date", fallback_text("Treatment Date", "تاريخ العلاج")), receipt_date or "—"),
            (translate_label("total_cost", fallback_text("Total Cost", "التكلفة الإجمالية")), format_currency(payment.get("total_amount_cents"))),
        ]
        if include_treatment and payment.get("treatment"):
            treatment_rows.insert(0, (translate_label("treatment", fallback_text("Treatment", "العلاج")), payment.get("treatment", "")))
        render_info_blocks(patient_block_title, patient_rows, translate_label("treatment", fallback_text("Treatment", "العلاج")), treatment_rows)
        if include_notes and payment.get("note"):
            render_text_panel(translate_label("sheet_notes", fallback_text("Notes", "ملاحظات")), payment["note"])

    elif format_type == "payment":
        render_header(meta_rows, logo_used)
        payment_only_rows = [
            (translate_label("payment_date", fallback_text("Payment Date", "تاريخ الدفع")), receipt_date or "—"),
            (translate_label("summary_paid", fallback_text("Paid", "المدفوع")), format_currency(payment.get("amount_cents"))),
            (translate_label("payment_method", fallback_text("Payment Method", "طريقة الدفع")), method_label),
            (translate_label("reference", fallback_text("Reference", "المرجع")), receipt_number),
        ]
        render_info_blocks(patient_block_title, patient_rows, translate_label("payment", fallback_text("Payment", "الدفع")), payment_only_rows)
        if include_treatment and payment.get("treatment"):
            render_text_panel(translate_label("treatment", fallback_text("Treatment", "العلاج")), payment["treatment"])
        if include_notes and payment.get("note"):
            render_text_panel(translate_label("sheet_notes", fallback_text("Notes", "ملاحظات")), payment["note"])

    elif format_type == "receipt":
        render_header(meta_rows, logo_used)
        compact_rows = [
            (translate_label("receipt_date_label", fallback_text("Date", "التاريخ")), receipt_date or "—"),
            (translate_label("summary_paid", fallback_text("Paid", "المدفوع")), format_currency(payment.get("amount_cents"))),
            (translate_label("payment_method", fallback_text("Payment Method", "طريقة الدفع")), method_label),
        ]
        render_info_blocks(patient_block_title, patient_rows, translate_label("receipt", fallback_text("Receipt", "إيصال")), compact_rows)
        if include_treatment and payment.get("treatment"):
            render_text_panel(translate_label("treatment", fallback_text("Treatment", "العلاج")), payment["treatment"])
        if include_notes and payment.get("note"):
            render_text_panel(translate_label("sheet_notes", fallback_text("Notes", "ملاحظات")), payment["note"])
    else:
        # Fallback to full layout if the format is unknown
        render_header(meta_rows, logo_used)
        render_info_blocks(patient_block_title, patient_rows, payments_block_title, payment_rows)
        if include_treatment and payment.get("treatment"):
            render_text_panel(translate_label("treatment", fallback_text("Treatment", "العلاج")), payment["treatment"])
        if include_notes and payment.get("note"):
            render_text_panel(translate_label("sheet_notes", fallback_text("Notes", "ملاحظات")), payment["note"])

    # Enhanced professional footer
    pdf.ln(8)
    
    # Receipt metadata and QR code area
    receipt_id = payment.get('id', '')[:8].upper() if payment.get('id') else "N/A"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Get localized footer texts
    def translate_line(key: str, fallback_en: str, fallback_ar: str, **fmt) -> str:
        text = translate_text(locale, key, **fmt)
        if text == key:
            template = fallback_ar if locale == "ar" else fallback_en
            return template.format(**fmt)
        return text

    footer_lines = [
        translate_line("receipt_id_label", "Receipt ID: {receipt_id}", "رقم الإيصال: {receipt_id}", receipt_id=receipt_id),
        translate_line("generated_label", "Generated: {current_time}", "تاريخ الطباعة: {current_time}", current_time=current_time),
        translate_line("thank_you_message", "Thank you for choosing our clinic!", "شكرا لاختيار عيادتنا!"),
    ]
    footer_texts = [shape_text(line) if pdf._rtl_mode else line for line in footer_lines]
    
    # Centered footer block (text over QR)
    pdf.ln(6)
    center_x = (pdf.w - pdf.l_margin - pdf.r_margin) / 2 + pdf.l_margin
    pdf.set_font(pdf._family, "", 8)
    block_width = pdf.w - pdf.l_margin - pdf.r_margin
    for text in footer_texts:
        pdf.set_xy(pdf.l_margin, pdf.y)
        pdf.cell(block_width, 4, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    
    # Add QR code if requested (centered under the footer text)
    if include_qr:
        pdf.ln(2)
        qr_size = 20
        qr_x = center_x - (qr_size / 2)
        qr_y = pdf.y
        
        # Generate QR code data payload
        qr_payload = {
            "number": receipt_id,
            "date": current_time[:10],
            "amount": f"{payment.get('amount_cents', 0)/100:.2f} {currency_label}",
            "patient": patient.get("full_name", ""),
            "clinic": treatment_details.get("clinic_name", "Dental Clinic")
        }
        
        import json
        qr_data = json.dumps(qr_payload, ensure_ascii=False, separators=(',', ':'))
        
        # Add actual QR code
        pdf.add_qr_code(qr_data, qr_x, qr_y, qr_size)
    
    return pdf.render()


def _add_watermark(pdf: ReceiptPDF, text: str, locale: str = "en") -> None:
    """Add watermark to PDF."""
    from clinic_app.services.i18n import translate_text
    
    # Get localized watermark text
    watermark_text = translate_text(locale, "copy_watermark")
    if watermark_text == "copy_watermark":  # Fallback if translation not found
        watermark_text = "CLINIC COPY" if locale == "en" else "نسخة العيادة"
    
    pdf.set_text_color(210, 210, 210)
    try:
        pdf.set_alpha(0.2)  # type: ignore[attr-defined]
    except Exception:
        pass
    pdf.set_font(pdf._family, "B", 60)

    # Shape watermark text if needed
    shaped_text = pdf._shape_if_arabic(watermark_text) if locale == "ar" else watermark_text

    # Center watermark without forcing a new page
    current_y = pdf.y
    center_x = (pdf.w - pdf.l_margin - pdf.r_margin) / 2 + pdf.l_margin
    center_y = (pdf.h - pdf.t_margin - pdf.b_margin) / 2 + pdf.t_margin
    pdf.set_xy(center_x - 40, center_y)
    pdf.cell(120, 30, shaped_text, align="C")

    pdf.set_text_color(0, 0, 0)  # Reset to black
    try:
        pdf.set_alpha(1)  # type: ignore[attr-defined]
    except Exception:
        pass
    pdf.set_xy(pdf.l_margin, current_y)


def generate_receipt_pdf(data: dict, receipt_type: str, format_options: dict = None, locale: str = "en", print_options: dict = None) -> bytes:
    """Main function to generate receipts based on type and format with Arabic support."""
    if format_options is None:
        format_options = {}
    
    if print_options is None:
        print_options = {}
    
    if receipt_type == "expense":
        return generate_expense_receipt_pdf(
            data["expense_receipt"],
            data["materials"],
            data["supplier"],
            data.get("settings", {})
        )
    elif receipt_type == "payment":
        return generate_payment_receipt_pdf(
            data["payment"],
            data["patient"],
            data.get("treatment_details", {}),
            format_options.get("format_type", "full") if format_options else "full",
            locale,
            print_options
        )
    else:
        raise ValueError(f"Unknown receipt type: {receipt_type}")
