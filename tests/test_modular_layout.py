import importlib, pathlib

def test_package_exists():
    root = pathlib.Path(__file__).resolve().parents[1]
    assert (root / "clinic_app" / "blueprints" / "images" / "images.py").exists(), "images blueprint file missing"
    assert (root / "wsgi.py").exists(), "wsgi.py missing"

def test_imports_ok():
    # importing the app package should not raise
    pkg = importlib.import_module("clinic_app")
    assert hasattr(pkg, "create_app")
