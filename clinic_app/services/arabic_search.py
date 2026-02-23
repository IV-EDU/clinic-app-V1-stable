"""Arabic text normalization for search functionality."""

import re

def normalize_arabic(text: str | None) -> str | None:
    """
    Normalizes Arabic text for searching by unifying common character variations
    and removing diacritics (tashkeel).

    Rules:
    - Unifies Alef variants (أ, إ, آ) to bare Alef (ا)
    - Unifies Teh Marbuta (ة) to Heh (ه)
    - Unifies Alef Maksura (ى) to Yeh (ي)
    - Removes all Arabic diacritical marks
    - Lowercases text (to preserve case-insensitive search for English/Latin text)

    Args:
        text (str | None): The input text to normalize.

    Returns:
        str | None: The normalized text, or None if the input was None.
    """
    if text is None:
        return None

    # Remove diacritics (Tashkeel)
    # Range \u064B-\u065F covers Fathatan, Dammatan, Kasratan, Fatha, Damma, Kasra, Shadda, Sukun
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)

    # Normalize Alef variants -> bare Alef
    text = re.sub(r'[أإآ]', 'ا', text)

    # Normalize Teh Marbuta -> Heh
    text = re.sub(r'ة', 'ه', text)

    # Normalize Alef Maksura -> Yeh
    text = re.sub(r'ى', 'ي', text)

    # Normalize Tatweel (Kashida)
    text = re.sub(r'ـ', '', text)

    return text.lower()
