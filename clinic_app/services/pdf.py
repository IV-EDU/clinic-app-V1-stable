"""PDF utilities built on top of fpdf2 for bilingual receipts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from fpdf import FPDF, XPos, YPos


class ReceiptPDF(FPDF):
    """Enhanced helper around FPDF to render bilingual (EN/AR) receipts with Arabic support."""

    def __init__(self, font_path: str | None) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self._font_path = font_path
        self._family = "Helvetica"
        self._rtl_mode = False  # RTL text mode
        self._ensure_fonts()
        self.add_page()

    def _ensure_fonts(self) -> None:
        if self._font_path and Path(self._font_path).exists():
            try:
                self.add_font("DejaVu", "", self._font_path)
                self.add_font("DejaVu", "B", self._font_path)
                self._family = "DejaVu"
                self.set_font(self._family, "B", 18)
            except Exception:
                # Fallback to Helvetica if font loading fails
                self._family = "Helvetica"
                self.set_font(self._family, "B", 18)
        else:
            self._family = "Helvetica"
            self.set_font(self._family, "B", 18)

    def set_rtl_mode(self, enabled: bool) -> None:
        """Enable or disable RTL (right-to-left) mode for Arabic text."""
        self._rtl_mode = enabled

    def _normalize_arabic_text(self, text: str) -> str:
        """Normalize Arabic text for proper rendering."""
        if not self._rtl_mode or not self._is_arabic_text(text):
            return text
        
        # Remove zero-width spaces and other formatting characters
        text = text.replace('\u200B', '')  # Zero width space
        text = text.replace('\u200C', '')  # Zero width non-joiner
        text = text.replace('\u200D', '')  # Zero width joiner
        
        return text

    def _is_arabic_text(self, text: str) -> bool:
        """Check if text contains Arabic characters."""
        arabic_chars = [c for c in text if 0x0600 <= ord(c) <= 0x06FF]
        return len(arabic_chars) > 0

    def heading(self, text_en: str, text_ar: str) -> None:
        """Render bilingual heading with proper text direction."""
        self.set_font(self._family, "B", 18)
        
        # Use current FPDF2 API instead of deprecated ln parameter
        self.cell(0, 10, text_en, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font_size(14)
        self.cell(0, 8, text_ar, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(4)

    def kv_block(self, rows: Iterable[tuple[str, str]]) -> None:
        """Render key-value block with improved API."""
        self.set_font(self._family, "", 12)
        width = max(0.1, self.w - self.l_margin - self.r_margin)
        
        for label, value in rows:
            text = f"{label}: {value}"
            self.multi_cell(width, 7, text, border=0, new_x=XPos.LMARGIN)
        self.ln(3)

    def note(self, text: str) -> None:
        """Render note text with improved API."""
        self.set_font(self._family, "", 11)
        self.multi_cell(0, 6, text, border=0, new_x=XPos.LMARGIN)
        self.ln(2)

    def render(self) -> bytes:
        """Render the PDF and return as bytes."""
        output = self.output()
        if isinstance(output, str):
            return output.encode("latin1")
        return bytes(output)
