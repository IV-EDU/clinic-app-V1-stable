from __future__ import annotations

import io, time, zipfile, re, hashlib
from pathlib import Path
from flask import render_template, send_file, send_from_directory, jsonify, request, redirect, url_for
import os, sqlite3, uuid, json
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from flask import Blueprint, current_app, request, jsonify, render_template
from clinic_app.services.theme_settings import get_theme_variables

from clinic_app.services.security import require_permission
from clinic_app.extensions import csrf
from clinic_app.services.csrf import ensure_csrf_token

def _theme_css() -> str:
    vars = get_theme_variables()
    parts = []
    if vars:
        overrides = []
        primary = vars.get("primary_color")
        accent = vars.get("accent_color")
        base_font = vars.get("base_font_size")
        text_color = vars.get("text_color")
        if primary:
            overrides.append(f"--primary-color: {primary};")
        if accent:
            overrides.append(f"--accent-color: {accent};")
        if base_font:
            try:
                size_val = int(float(base_font))
                clamped = max(14, min(size_val, 18))
                overrides.append(f"font-size: clamp(14px, {clamped}px, 18px);")
            except Exception:
                pass
        if text_color:
            overrides.append(f"--ink: {text_color};")
            overrides.append(f"--text-primary: {text_color};")
        if overrides:
            parts.append(":root { " + " ".join(overrides) + " }")
    return "\n".join(parts)

def _db_path():
    app = current_app
    return app.config.get("PALMER_PLUS_DB", os.path.join(app.root_path, "data/app.db"))

def _connect():
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def _clinic_db_path():
    return _db_path()

def _clinic_connect():
    return _connect()

def _fetch_patient(pid:str)->dict:
    try:
        conn = _clinic_connect(); cur = conn.cursor()
        cur.execute("SELECT id, short_id, full_name, phone, notes, created_at FROM patients WHERE id=?", (pid,))
        row = cur.fetchone()
        conn.close()
        if not row: return {}
        return dict(row)
    except Exception:
        return {}

def _init_db():
    c = _connect(); cur = c.cursor()
    cur.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS diagnosis (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        chart_type TEXT NOT NULL,
        tooth_code TEXT NOT NULL,
        status TEXT,
        note TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(patient_id, chart_type, tooth_code)
    );
    CREATE TABLE IF NOT EXISTS diagnosis_event(
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        chart_type TEXT NOT NULL,
        tooth_code TEXT NOT NULL,
        action TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT,
        note TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS medical (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL UNIQUE,
        problems TEXT,
        allergies_flag INTEGER DEFAULT 0,
        allergies TEXT,
        vitals TEXT,
        notes TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS medical_event (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        action TEXT NOT NULL,
        old_json TEXT,
        new_json TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    c.commit(); c.close()

bp = Blueprint("palmer_plus", __name__, url_prefix="/patients/<pid>", template_folder="../../templates", static_folder="../../static")

@bp.before_app_request
def _ensure():
    if request.blueprint == "palmer_plus":
        _init_db()

ADULT = ["1","2","3","4","5","6","7","8"]
CHILD = ["A","B","C","D","E"]

def build_adult()->Tuple[List[str],List[str],List[str],List[str]]:
    upper_right = ["UR"+n for n in ADULT[::-1]]
    upper_left  = ["UL"+n for n in ADULT]
    lower_right = ["LR"+n for n in ADULT[::-1]]
    lower_left  = ["LL"+n for n in ADULT]
    return upper_right, upper_left, lower_right, lower_left

def build_child()->Tuple[List[str],List[str],List[str],List[str]]:
    upper_right = ["UR"+c for c in CHILD[::-1]]
    upper_left  = ["UL"+c for c in CHILD]
    lower_right = ["LR"+c for c in CHILD[::-1]]
    lower_left  = ["LL"+c for c in CHILD]
    return upper_right, upper_left, lower_right, lower_left

STATUS = ["Healthy","Caries","Filled","Missing","RCT","Crown","Implant","Note"]
CHOICES = [("", "—")] + [(s,s) for s in STATUS]
COLORS = {
    "":        "#ffffff",
    "Healthy": "#10b981",
    "Caries":  "#ef4444",
    "Filled":  "#3b82f6",
    "Missing": "#9ca3af",
    "RCT":     "#a855f7",
    "Crown":   "#f59e0b",
    "Implant": "#0ea5e9",
    "Note":    "#06b6d4",
}

def _fetch_states(conn, pid:str, chart_type:str)->Dict[str, Dict[str,str]]:
    rows = conn.execute("SELECT tooth_code,status,note,updated_at FROM diagnosis WHERE patient_id=? AND chart_type=?", (pid, chart_type)).fetchall()
    out = {}
    for r in rows:
        st = r["status"] or ""
        out[r["tooth_code"]] = {"status": st, "note": r["note"] or "", "updated_at": r["updated_at"]}
    return out

def _fetch_medical(conn, pid:str)->Dict[str, Any]:
    r = conn.execute("SELECT problems, allergies_flag, allergies, vitals, updated_at FROM medical WHERE patient_id=?",(pid,)).fetchone()
    if not r:
        return {"medical_notes":"", "allergies_flag":0, "allergies":"", "vitals":"{}", "updated_at":""}
    return {
        "medical_notes": r["problems"] or "",
        "allergies_flag": int(r["allergies_flag"] or 0),
        "allergies": r["allergies"] or "",
        "vitals": r["vitals"] or "{}",
        "updated_at": r["updated_at"] or ""
    }

def _parse_flags(vitals_json:str)->Dict[str,Any]:
    def b(x):
        try: return bool(x)
        except: return False
    try:
        v = json.loads(vitals_json or "{}") or {}
    except Exception:
        v = {}
    return {
        # existing
        "anticoag": b(v.get("anticoag")),
        "prophy": b(v.get("prophy")),
        "dm_uncontrolled": b(v.get("dm_uncontrolled")),
        # new
        "pregnancy": b(v.get("pregnancy")),
        "smoking_vaping": b(v.get("smoking_vaping")),
        "bisphosphonates_denosumab": b(v.get("bisphosphonates_denosumab")),
        "bleeding_disorder": b(v.get("bleeding_disorder")),
        "immunosuppression": b(v.get("immunosuppression")),
        "prosthetic_valve": b(v.get("prosthetic_valve")),
        "pacemaker_icd": b(v.get("pacemaker_icd")),
        "latex_allergy": b(v.get("latex_allergy")),
    }

@bp.get("/")
@require_permission("patients:view")
def index(pid):
    """Redirect to diagnosis page."""
    return redirect(url_for("palmer_plus.diag_page", pid=pid))

@bp.get("/diagnosis/")
@require_permission("patients:view")
def diag_page(pid):
    chart = (request.args.get("chart") or "adult").lower()
    chart_type = "child" if chart=="child" else "adult"
    conn = _connect()
    states = _fetch_states(conn, pid, chart_type)
    med = _fetch_medical(conn, pid)
    conn.close()
    flags = _parse_flags(med.get("vitals","{}"))
    if chart_type == "adult":
        UR, UL, LR, LL = build_adult()
    else:
        UR, UL, LR, LL = build_child()
    def lab(code:str)->str: return code[-1]
    # banner dict includes criticals
    return render_template("diag_plus/diagnosis.html", patient=_fetch_patient(pid), pid=pid, chart_type=chart_type,
        UR=[(c, lab(c)) for c in UR],
        UL=[(c, lab(c)) for c in UL],
        LR=[(c, lab(c)) for c in LR],
        LL=[(c, lab(c)) for c in LL],
        states=states,
        state_short={k:(v.get('status') or '') for k,v in states.items()},
        js={"states": states},
        colors=COLORS, status_choices=CHOICES,
        med_banner={
            "allergies_flag": med.get("allergies_flag",0), "allergies": med.get("allergies",""),
            "pregnancy": flags["pregnancy"],
            "bleeding_disorder": flags["bleeding_disorder"],
            "bisphosphonates_denosumab": flags["bisphosphonates_denosumab"],
        },
        med_chips={
            "anticoag": flags["anticoag"],
            "prophy": flags["prophy"],
            "dm_uncontrolled": flags["dm_uncontrolled"],
            "smoking_vaping": flags["smoking_vaping"],
            "immunosuppression": flags["immunosuppression"],
            "prosthetic_valve": flags["prosthetic_valve"],
            "pacemaker_icd": flags["pacemaker_icd"],
            "latex_allergy": flags["latex_allergy"],
        },
        theme_css=_theme_css(),
    )

@bp.post("/diagnosis/api/set")
@csrf.exempt
@require_permission("patients:edit")
def diag_set(pid):
    data = request.get_json(silent=True) or {}
    ensure_csrf_token(data)
    chart_type = "child" if (data.get("chart_type") or "").lower()=="child" else "adult"
    code = (data.get("tooth_code") or "").strip()
    status = (data.get("status") or "").strip()
    has_note_key = ("note" in data)
    note_in = data.get("note", None)
    clear = bool(data.get("clear"))
    explicit_white = ("status" in data and (data.get("status") or "") == "")
    if not code:
        return jsonify(ok=False, error="Missing tooth_code"), 400

    conn = _connect(); cur = conn.cursor()
    prev = cur.execute("SELECT id,status,note FROM diagnosis WHERE patient_id=? AND chart_type=? AND tooth_code=?",
                       (pid, chart_type, code)).fetchone()

    if clear:
        if prev:
            cur.execute("DELETE FROM diagnosis WHERE id=?", (prev["id"],))
        conn.commit(); conn.close()
        return jsonify(ok=True, state=None)

    prev_status = (prev["status"] if prev else "") or ""
    prev_note = (prev["note"] if prev else "") or ""

    # Decide the note to save
    if not has_note_key:
        note = prev_note
    else:
        # If client sent empty string, treat as 'no change' (avoid accidental wipe)
        if note_in is None:
            note = prev_note
        elif isinstance(note_in, str) and note_in.strip() == "":
            note = prev_note
        else:
            note = str(note_in).strip()

    # Do NOT auto-set a color when only a note exists; keep previous status unless explicitly provided
    if explicit_white:
        saved_status = ""
    elif status:
        saved_status = status
    else:
        saved_status = prev_status

    now = datetime.now(timezone.utc).isoformat()
    if prev:
        cur.execute("UPDATE diagnosis SET status=?, note=?, updated_at=? WHERE id=?",
                    (saved_status, note, now, prev["id"]))
    else:
        cur.execute("INSERT INTO diagnosis VALUES (?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), pid, chart_type, code, saved_status, note, now))
    conn.commit(); conn.close()
    return jsonify(ok=True, state={"status": saved_status, "note": note, "updated_at": now})
def _flags_from_payload(data:Dict[str,Any])->Dict[str,bool]:
    keys = [
        "anticoag","prophy","dm_uncontrolled","pregnancy","smoking_vaping",
        "bisphosphonates_denosumab","bleeding_disorder","immunosuppression",
        "prosthetic_valve","pacemaker_icd","latex_allergy"
    ]
    return {k: bool(data.get(k)) for k in keys}

@bp.get("/medical/")
@require_permission("patients:view")
def med_page(pid):
    conn = _connect()
    data = _fetch_medical(conn, pid)
    flags = _parse_flags(data.get("vitals","{}"))
    conn.close()
    return render_template("diag_plus/medical.html", patient=_fetch_patient(pid), pid=pid, data=data, flags=flags, theme_css=_theme_css())

@bp.post("/medical/api/save")
@csrf.exempt
@require_permission("patients:edit")
def med_save(pid):
    data = request.get_json(silent=True) or {}
    ensure_csrf_token(data)
    conn = _connect(); cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    vitals = _flags_from_payload(data)
    med_notes = (data.get("medical_notes","") or "").strip()
    allergies_flag = 1 if data.get("allergies_flag") else 0
    allergies = (data.get("allergies","") or "").strip()

    row = cur.execute("SELECT id, problems, allergies_flag, allergies, vitals FROM medical WHERE patient_id=?",(pid,)).fetchone()
    new_json = json.dumps({"medical_notes":med_notes,"allergies_flag":allergies_flag,"allergies":allergies,"vitals":vitals}, ensure_ascii=False)
    if row:
        old_json = json.dumps({"medical_notes":row["problems"],"allergies_flag":row["allergies_flag"],"allergies":row["allergies"],"vitals":row["vitals"]}, ensure_ascii=False)
        cur.execute("""UPDATE medical SET problems=?, allergies_flag=?, allergies=?, vitals=?, updated_at=? WHERE id=?""",
                    (med_notes, allergies_flag, allergies, json.dumps(vitals, ensure_ascii=False), now, row["id"]))
        cur.execute("INSERT INTO medical_event VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), pid, "set", old_json, new_json, now))
    else:
        nid = str(uuid.uuid4())
        cur.execute("""INSERT INTO medical(id,patient_id,problems,allergies_flag,allergies,vitals,notes,updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (nid, pid, med_notes, allergies_flag, allergies, json.dumps(vitals, ensure_ascii=False), "", now))
        cur.execute("INSERT INTO medical_event VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), pid, "set", None, new_json, now))
    conn.commit(); conn.close()
    return jsonify(ok=True, updated_at=now)

# --- Patient images storage helpers & routes ---
def _patient_images_dir(pid:int) -> Path:
    data_root = Path(current_app.config.get("DATA_ROOT", Path(current_app.root_path) / "data"))
    root = (data_root / 'patient_images' / str(pid))
    root.mkdir(parents=True, exist_ok=True)
    return root

@bp.route("/images")
@require_permission("patients:view")
def images_page(pid):
    chart_type = request.args.get("chart_type","adult")
    pdir = _patient_images_dir(pid)
    images = []
    for p in sorted(pdir.glob("*")):
        if p.is_file():
            images.append({"name": p.name, "size": p.stat().st_size})
    return render_template("diag_plus/images.html", pid=pid, chart_type=chart_type, images=images, theme_css=_theme_css())

@bp.route("/images/upload", methods=["POST"])
@require_permission("patients:edit")
def upload_patient_images(pid):
    pdir = _patient_images_dir(pid)
    files = request.files.getlist("files")
    saved = 0
    duplicates = 0
    errors = 0

    # Build hash index of existing files (sha256 of bytes)
    existing = {}
    for p in pdir.glob("*"):
        if p.is_file():
            try:
                h = hashlib.sha256(p.read_bytes()).hexdigest()
                existing[h] = p.name
            except Exception:
                pass

    for f in files:
        try:
            if not f or not getattr(f, "filename", ""):
                continue
            raw = f.read()  # read into memory for hashing
            if not raw:
                continue
            new_hash = hashlib.sha256(raw).hexdigest()
            if new_hash in existing:
                duplicates += 1
                continue
            # sanitize name
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", f.filename or "")
            # avoid overwrite on name collision
            dest = pdir / name
            if dest.exists():
                dest = pdir / f"{dest.stem}_{int(time.time())}{dest.suffix}"
            with open(dest, "wb") as w:
                w.write(raw)
            existing[new_hash] = dest.name
            saved += 1
        except Exception:
            errors += 1
            continue
    return jsonify({"ok": True, "saved": saved, "duplicates": duplicates, "errors": errors})

@bp.route("/images/file/<path:filename>")
@require_permission("patients:view")
def get_patient_image(pid, filename):
    pdir = _patient_images_dir(pid)
    return send_from_directory(pdir.as_posix(), filename, as_attachment=False)

@bp.route("/images/export_all")
@require_permission("patients:edit")
def export_all_images(pid):
    pdir = _patient_images_dir(pid)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for p in pdir.glob("*"):
            if p.is_file():
                z.write(p.as_posix(), arcname=p.name)
    mem.seek(0)
    return send_file(mem, mimetype="application/zip", as_attachment=True, download_name=f"patient_{pid}_images.zip")

@bp.route("/images/export_selected", methods=["GET","POST"])
@require_permission("patients:edit")
def export_selected_images(pid):
    # Accept selection via GET (?files=JSON or CSV) or POST (form field 'files' JSON/CSV)
    names = []
    if request.method == "POST":
        raw = request.form.get("files", "")
    else:
        raw = request.args.get("files", "")
    if raw:
        try:
            import json as _json
            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                names = [str(x) for x in parsed if x]
        except Exception:
            # fall back to CSV
            names = [x for x in raw.split(",") if x]

    # Empty selection -> go back with message
    if not names:
        chart_type = request.args.get("chart_type","adult")
        return redirect(url_for('palmer_plus.images_page', pid=pid, chart_type=chart_type, msg="no_selection"))

    # Build zip
    pdir = _patient_images_dir(pid)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in names:
            p = pdir / n
            if p.is_file():
                zf.write(p.as_posix(), arcname=p.name)
    mem.seek(0)
    return send_file(mem, mimetype="application/zip", as_attachment=True,
                     download_name=f"patient_{pid}_images_selected.zip")
@bp.route("/images/delete", methods=["POST"])
@require_permission("patients:edit")
def delete_patient_images(pid):
    pdir = _patient_images_dir(pid)
    try:
        payload = request.get_json(silent=True) or {}
        names = payload.get("names") or []
        if isinstance(names, str):
            names = [names]
    except Exception:
        names = []
    deleted = 0
    for n in names:
        p = pdir / n
        try:
            if p.is_file():
                p.unlink()
                deleted += 1
        except Exception:
            pass
    return jsonify({"ok": True, "deleted": deleted})

@bp.route("/images/rename", methods=["POST"])
@require_permission("patients:edit")
def rename_patient_image(pid):
    pdir = _patient_images_dir(pid)
    data = request.get_json(silent=True) or {}
    old = data.get("old")
    new = data.get("new")
    if not old or not new:
        return jsonify({"ok": False, "error": "missing parameters"}), 400
    # sanitize new
    new = re.sub(r"[^A-Za-z0-9._-]+", "_", new)
    src = pdir / old
    if not src.is_file():
        return jsonify({"ok": False, "error": "not found"}), 404
    dest = pdir / new
    if dest.exists():
        dest = pdir / f"{dest.stem}_{int(time.time())}{dest.suffix}"
    try:
        src.rename(dest)
        return jsonify({"ok": True, "name": dest.name})
    except Exception as e:
        return jsonify({"ok": False, "error": "rename failed"}), 500


@bp.route("/images/export_selected_get", methods=["GET"])
@require_permission("patients:view")
def export_selected_images_alias(pid):
    # forward to main handler (supports GET)
    return export_selected_images(pid)
