from clinic_app.services.import_first_stable import _parse_date_from_text


def test_parse_date_single_ok():
    assert _parse_date_from_text("2023-09-17") == "2023-09-17"
    assert _parse_date_from_text("17/09/2023") == "2023-09-17"


def test_parse_date_range_returns_blank():
    assert _parse_date_from_text("17/09/2023-23/03/2023") == ""
    assert _parse_date_from_text("10/09/23 - 24/09/23") == ""
    assert _parse_date_from_text("17/09/2023 إلى 23/03/2023") == ""
    assert _parse_date_from_text("17/09/2023-23/03") == ""


def test_parse_date_garbage_returns_blank():
    assert _parse_date_from_text("") == ""
    assert _parse_date_from_text("not a date") == ""

