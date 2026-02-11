import importlib


def test_wiring_runs_before_first_request(app):
    with app.test_request_context('/'):
        app.preprocess_request()


def test_core_globals_wired(app):
    core = importlib.import_module("clinic_app.blueprints.core.core")
    with app.test_request_context('/'):
        app.preprocess_request()
    assert callable(core.render_page), "render_page should be wired and callable"
    assert isinstance(core.BASE, str) and len(core.BASE) > 0, "BASE template should be wired"


def test_new_patient_page_does_not_500(logged_in_client):
    r = logged_in_client.get('/patients/new')
    assert r.status_code < 500, f"/patients/new returned {r.status_code}"
