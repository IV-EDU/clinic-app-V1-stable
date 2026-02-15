"""
Arabic character normalization service for search functionality.

This module provides functions to normalize Arabic text for consistent
search and comparison operations.
"""

import re


def normalize_arabic(text: str) -> str:
    """
    Normalize Arabic character variants in the given text.

    Collapses common Arabic letter variants to their base form:
    - Alef variants: ا, أ, إ, آ -> ا
    - Ta marbuta: ه, ة -> ه
    - Yeh variants: ي, ى -> ي

    Args:
        text: The input text to normalize.

    Returns:
        The normalized text, or original if no Arabic detected.
    """
    if not text:
        return text

    # Check if text contains Arabic characters
    if not any('\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' for c in text):
        return text

    # Mapping of Arabic character variants to their normalized forms
    normalization_map = {
        # Alef variants -> Alef
        'أ': 'ا',
        'إ': 'ا',
        'آ': 'ا',
        # Ta marbuta -> Heh
        'ة': 'ه',
        # Yeh variants -> Yeh
        'ى': 'ي',
    }

    result = []
    for char in text:
        result.append(normalization_map.get(char, char))

    return ''.join(result)


def normalize_search_query(query: str) -> str:
    """
    Normalize a search query for consistent matching.

    Applies Arabic normalization, strips extra whitespace,
    and lowercases the result for case-insensitive search.

    Args:
        query: The search query to normalize.

    Returns:
        Normalized search query ready for comparison.
    """
    if not query:
        return ''

    # Normalize Arabic characters
    normalized = normalize_arabic(query)

    # Strip extra whitespace (multiple spaces -> single space)
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # Lowercase for case-insensitive comparison
    normalized = normalized.lower()

    return normalized


# =============================================================================
# Unit Tests
# =============================================================================

if __name__ == '__main__':
    import sys

    def test_normalize_arabic():
        """Test Arabic character normalization."""
        # Test empty input
        assert normalize_arabic('') == ''
        assert normalize_arabic(None) is None

        # Test Alef variants
        assert normalize_arabic('أحمد') == 'احمد'
        assert normalize_arabic('إبراهيم') == 'ابراهيم'
        assert normalize_arabic('آسيا') == 'اسيا'

        # Test Ta marbuta
        assert normalize_arabic('مريم') == 'مريم'

        # Test Yeh variant
        assert normalize_arabic('على') == 'علي'

        # Test mixed
        assert normalize_arabic('أحمد علي') == 'احمد علي'

        # Test no Arabic
        assert normalize_arabic('hello world') == 'hello world'
        assert normalize_arabic('12345') == '12345'

        print('All normalize_arabic tests passed!')

    def test_normalize_search_query():
        """Test search query normalization."""
        # Test empty
        assert normalize_search_query('') == ''
        assert normalize_search_query('   ') == ''

        # Test basic normalization
        assert normalize_search_query('أحمد') == 'احمد'
        assert normalize_search_query('ahmad') == 'ahmad'

        # Test whitespace stripping
        assert normalize_search_query('  احمد   ') == 'احمد'
        assert normalize_search_query('احمد    علي') == 'احمد علي'

        # Test lowercase
        assert normalize_search_query('AHMED') == 'ahmed'
        assert normalize_search_query('أحمد') == 'احمد'

        # Test combined
        assert normalize_search_query('  أحمد   علي  ') == 'احمد علي'

        print('All normalize_search_query tests passed!')

    # Run tests
    try:
        test_normalize_arabic()
        test_normalize_search_query()
        print('\n✓ All tests passed successfully!')
        sys.exit(0)
    except AssertionError as e:
        print(f'\n✗ Test failed: {e}')
        sys.exit(1)
    except Exception as e:
        print(f'\n✗ Error: {e}')
        sys.exit(1)
