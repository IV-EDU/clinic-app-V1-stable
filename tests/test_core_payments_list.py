import importlib


def test_payments_list_template_wired(app):
    core = importlib.import_module("clinic_app.blueprints.core.core")
    with app.test_request_context('/'):
        app.preprocess_request()
    assert isinstance(core.PAYMENTS_LIST, str) and len(core.PAYMENTS_LIST) > 0, "PAYMENTS_LIST template should be wired"
