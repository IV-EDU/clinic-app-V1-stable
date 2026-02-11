# PyInstaller spec for Clinic App (offline Windows build).
#
# Builds a folder-based app (recommended) that can be zipped and shipped as a single file.
# Runtime data is kept in a local `data/` folder next to the executable (see clinic_app/__init__.py).
#
# Build (Windows):
#   py -3.12 -m pip install -r requirements.txt -r requirements.dev.txt
#   py -3.12 -m PyInstaller --noconfirm clinic_app.spec

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# NOTE: PyInstaller executes spec files in a context where __file__ may be undefined.
# Use SPECPATH when available.
project_root = Path(globals().get("SPECPATH", Path.cwd())).resolve()

hiddenimports = []
hiddenimports += collect_submodules("flask_wtf")
hiddenimports += collect_submodules("flask_login")
hiddenimports += collect_submodules("flask_limiter")
hiddenimports += collect_submodules("sqlalchemy")
hiddenimports += collect_submodules("PIL")

datas = []
datas += [(str(project_root / "templates"), "templates")]
datas += [(str(project_root / "static"), "static")]
datas += [(str(project_root / "migrations"), "migrations")]
datas += [(str(project_root / "alembic.ini"), ".")]
datas += collect_data_files("flask", include_py_files=False)
datas += collect_data_files("flask_wtf", include_py_files=False)

block_cipher = None

a = Analysis(
    ["wsgi.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClinicApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ClinicApp",
)
