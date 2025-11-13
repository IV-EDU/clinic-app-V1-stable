import importlib


def test_core_helper_migration_wired(app):
    core = importlib.import_module("clinic_app.blueprints.core.core")
    with app.test_request_context('/'):
        app.preprocess_request()
    assert callable(core._migrate_patients_drop_unique_short_id), "Migration helper should be wired as a callable"
