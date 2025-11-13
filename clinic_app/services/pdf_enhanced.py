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
        if self._font_path and Path(self._font_path).exists():
            try:
                font_name = "Cairo" if "cairo" in self._font_path.lower() else "DejaVu"
                self.add_font(font_name, "", self._font_path)
                self.add_font(font_name, "B", self._font_path)
                self._family = font_name
                self.set_font(self._family, "B", 18)
            except Exception as e:
                print(f"Font loading failed: {e}, falling back to Helvetica")
                self._family = "Helvetica"
                self.set_font(self._family, "B", 18)
        else:
            self._family = "Helvetica"
            self.set_font(self._family, "B", 18)

    def set_rtl_mode(self, enabled: bool) -> None:
        """Enable or disable RTL (right-to-left) mode for Arabic text."""
        self._rtl_mode = enabled
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
                return get_display(reshaped)
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
            # Arabic heading
            self.set_rtl_mode(True)
            ar_txt = self._shape_if_arabic(heading_text)
            self.cell(0, 10, ar_txt, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_font_size(14)
        else:
            # English heading
            self.cell(0, 10, heading_text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_font_size(14)
        
        self.set_rtl_mode(False)
        self.ln(4)

    def kv_block(self, rows: Iterable[tuple[str, str]], locale: str = "en") -> None:
        """Render professional key-value block with proper RTL support."""
        from clinic_app.services.i18n import translate_text
        
        # Add a subtle background for the key-value section
        self.set_fill_color(250, 250, 250)
        self.set_font(self._family, "", 11)
        width = max(0.1, self.w - self.l_margin - self.r_margin)
        
        # Create a bordered box for the key-value section
        box_height = len(rows) * 8 + 8
        self.set_draw_color(220, 220, 220)
        self.rect(self.l_margin, self.y, width, box_height, style='DF')
        
        current_y = self.y + 4
        
        for label, value in rows:
            # Draw separator line
            if current_y > self.y + 4:
                self.set_draw_color(235, 235, 235)
                self.line(self.l_margin + 2, current_y, self.w - self.r_margin - 2, current_y)
            
            # Render label (bold)
            self.set_font(self._family, "B", 11)
            
            # Get localized label if it's a key
            if label.startswith('key:'):
                key = label[4:]  # Remove 'key:' prefix
                if locale == "ar":
                    localized_label = translate_text("ar", key)
                    if localized_label == key:  # Fallback if not found
                        localized_label = key
                else:
                    localized_label = key
            else:
                localized_label = label
            
            # Add colon based on language direction
            if locale == "ar":
                label_text = f"{localized_label}:"
            else:
                label_text = f"{localized_label}:"
            
            # Render value (normal weight)
            self.set_font(self._family, "", 11)
            value_text = str(value)
            
            # Combine for Arabic text processing
            text = f"{label_text} {value_text}"
            
            # Shape/normalize Arabic when needed
            if self._is_arabic_text(text):
                text = self._shape_if_arabic(text)
            
            self.set_xy(self.l_margin + 4, current_y + 1)
            self.multi_cell(width - 8, 6, text, border=0, new_x=XPos.LMARGIN)
            current_y += 8
        
        self.ln(box_height + 2)

    def note(self, text: str) -> None:
        """Render note text with Arabic support."""
        self.set_font(self._family, "", 11)
        
        # Shape/normalize Arabic text
        shaped = self._shape_if_arabic(text) if self._rtl_mode else text
        self.multi_cell(0, 6, shaped, border=0, new_x=XPos.LMARGIN)
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
    if locale == "ar":
        ar_pref = (cfg.get("PDF_DEFAULT_ARABIC", "cairo") or "cairo").lower()
        ar_path = cfg.get("PDF_FONT_PATH_AR") if ar_pref == 'cairo' else cfg.get("PDF_FONT_PATH")
        font_path = ar_path or "static/fonts/DejaVuSans.ttf"
    else:
        font_path = cfg.get("PDF_FONT_PATH", "static/fonts/DejaVuSans.ttf")
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
    if locale == "ar":
        ar_pref = (cfg.get("PDF_DEFAULT_ARABIC", "cairo") or "cairo").lower()
        ar_path = cfg.get("PDF_FONT_PATH_AR") if ar_pref == 'cairo' else cfg.get("PDF_FONT_PATH")
        font_path = ar_path or "static/fonts/DejaVuSans.ttf"
    else:
        font_path = cfg.get("PDF_FONT_PATH", "static/fonts/DejaVuSans.ttf")
    
    pdf = ReceiptPDF(font_path=font_path, locale=locale)
    
    # Enable RTL mode for Arabic
    if locale == "ar":
        pdf.set_rtl_mode(True)
    
    # Add watermark if requested
    if add_watermark:
        _add_watermark(pdf, "CLINIC COPY", locale)
    
    # Common header
    pdf.clinic_header(
        treatment_details.get("clinic_name", "Dental Clinic"),
        treatment_details.get("clinic_address", ""),
        treatment_details.get("clinic_phone", "")
    )
    
    # Format-specific content with proper translation keys
    if format_type == "full":
        format_title = "Payment Receipt - Complete" if locale == "en" else "إيصال دفع - كامل"
        pdf.heading(format_title, locale)
        
        # Patient and payment information with translation keys
        rows = [
            ("key:patient_name", patient.get("full_name", "")),
            ("key:file_no", patient.get("short_id", "")),
            ("key:payment_date", payment.get("paid_at", "")),
            ("key:payment_method", payment.get("method", "")),
            ("key:total_amount", f"{payment.get('total_amount_cents', 0)/100:.2f} EGP"),
            ("key:discount", f"{payment.get('discount_cents', 0)/100:.2f} EGP"),
            ("key:paid_amount", f"{payment.get('amount_cents', 0)/100:.2f} EGP"),
            ("key:remaining_balance", f"{payment.get('remaining_cents', 0)/100:.2f} EGP"),
        ]
        if include_treatment and payment.get("treatment"):
            rows.append(("key:treatment", payment.get("treatment", "")))
        pdf.kv_block(rows, locale)
        
        # Treatment details - only if both switches are on
        if include_notes and include_treatment and payment.get("treatment"):
            pdf.ln(4)
            pdf.set_font(pdf._family, "B", 12)
            treatment_details_label = "Treatment Details:" if locale == "en" else "تفاصيل العلاج:"
            pdf.cell(0, 8, treatment_details_label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.note(f"Treatment: {payment['treatment']}" if locale == "en" else f"العلاج: {payment['treatment']}")
        
        # Notes - only if include_notes is True
        if include_notes and payment.get("note"):
            pdf.ln(2)
            notes_label = "Notes:" if locale == "en" else "ملاحظات:"
            pdf.cell(0, 8, notes_label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.note(payment["note"])
    
    elif format_type == "summary":
        format_title = "Payment Receipt - Summary" if locale == "en" else "إيصال دفع - ملخص"
        pdf.heading(format_title, locale)
        
        rows = [
            ("key:patient", patient.get("full_name", "")),
            ("key:file_no", patient.get("short_id", "")),
            ("key:date", payment.get("paid_at", "")),
            ("key:amount_paid", f"{payment.get('amount_cents', 0)/100:.2f} EGP"),
            ("key:method", payment.get("method", "")),
        ]
        if include_treatment and payment.get("treatment"):
            rows.append(("key:treatment", payment.get("treatment", "")))
        pdf.kv_block(rows, locale)
    
    elif format_type == "treatment":
        format_title = "Treatment Receipt" if locale == "en" else "إيصال علاج"
        pdf.heading(format_title, locale)
        
        rows = [
            ("key:patient", patient.get("full_name", "")),
            ("key:file_no", patient.get("short_id", "")),
            ("key:treatment_date", payment.get("paid_at", "")),
            ("key:total_cost", f"{payment.get('total_amount_cents', 0)/100:.2f} EGP"),
        ]
        if include_treatment:
            rows.insert(3, ("key:treatment", payment.get("treatment", "General Treatment" if locale == "en" else "علاج عام")))
        pdf.kv_block(rows, locale)
        
        # Treatment notes - only if include_notes is True
        if include_notes and payment.get("note"):
            pdf.ln(2)
            treatment_notes_label = "Treatment Notes:" if locale == "en" else "ملاحظات العلاج:"
            pdf.cell(0, 8, treatment_notes_label, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.note(payment["note"])
    
    elif format_type == "payment":
        format_title = "Payment Only" if locale == "en" else "دفع فقط"
        pdf.heading(format_title, locale)
        
        rows = [
            ("key:patient", patient.get("full_name", "")),
            ("key:payment_date", payment.get("paid_at", "")),
            ("key:amount", f"{payment.get('amount_cents', 0)/100:.2f} EGP"),
            ("key:method", payment.get("method", "")),
            ("key:reference", payment.get("id", "")[-8:].upper() if payment.get("id") else ""),  # Last 8 chars of payment ID
        ]
        if include_treatment and payment.get("treatment"):
            rows.append(("key:treatment", payment.get("treatment", "")))
        pdf.kv_block(rows, locale)

    elif format_type == "receipt":
        # Compact receipt style
        format_title = "Receipt" if locale == "en" else "إيصال"
        pdf.heading(format_title, locale)
        rows = [
            ("key:patient", patient.get("full_name", "")),
            ("key:date", payment.get("paid_at", "")),
            ("key:paid", f"{payment.get('amount_cents', 0)/100:.2f} EGP"),
            ("key:method", payment.get("method", "")),
        ]
        if include_treatment and payment.get("treatment"):
            rows.append(("key:treatment", payment.get("treatment", "")))
        pdf.kv_block(rows, locale)
    
    # Enhanced professional footer
    pdf.ln(8)
    
    # Draw footer separator line
    pdf.set_line_width(0.5)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.y, pdf.w - pdf.r_margin, pdf.y)
    pdf.ln(3)
    
    # Receipt metadata and QR code area
    receipt_id = payment.get('id', '')[:8].upper() if payment.get('id') else "N/A"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Get localized footer texts
    from clinic_app.services.i18n import translate_text
    
    if locale == "ar":
        footer_texts = [
            translate_text("ar", "receipt_id_label", receipt_id=receipt_id),
            translate_text("ar", "generated_label", current_time=current_time),
            translate_text("ar", "thank_you_message")
        ]
        # Fallback if translations not found
        if footer_texts[0] == "receipt_id_label":
            footer_texts[0] = f"رقم الإيصال: {receipt_id}"
        if footer_texts[1] == "generated_label":
            footer_texts[1] = f"تاريخ الطباعة: {current_time}"
        if footer_texts[2] == "thank_you_message":
            footer_texts[2] = "شكرا لاختيار عيادتنا!"
    else:
        footer_texts = [
            translate_text("en", "receipt_id_label", receipt_id=receipt_id),
            translate_text("en", "generated_label", current_time=current_time),
            translate_text("en", "thank_you_message")
        ]
        # Fallback if translations not found
        if footer_texts[0] == "receipt_id_label":
            footer_texts[0] = f"Receipt ID: {receipt_id}"
        if footer_texts[1] == "generated_label":
            footer_texts[1] = f"Generated: {current_time}"
        if footer_texts[2] == "thank_you_message":
            footer_texts[2] = "Thank you for choosing our clinic!"
    
    pdf.set_font(pdf._family, "", 8)
    for text in footer_texts:
        pdf.cell(0, 4, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    
    # Add QR code if requested (now with actual QR code generation)
    if include_qr:
        pdf.ln(2)
        qr_size = 15
        qr_x = (pdf.w - pdf.l_margin - pdf.r_margin - qr_size) / 2 + pdf.l_margin
        qr_y = pdf.y
        
        # Generate QR code data payload
        qr_payload = {
            "number": receipt_id,
            "date": current_time[:10],
            "amount": f"{payment.get('amount_cents', 0)/100:.2f} EGP",
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
    
    pdf.set_text_color(128, 128, 128)
    pdf.set_font(pdf._family, "B", 50)
    pdf.ln(120)
    
    # Shape watermark text if needed
    shaped_text = pdf._shape_if_arabic(watermark_text) if locale == "ar" else watermark_text
    
    pdf.cell(0, 20, shaped_text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)  # Reset to black


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
