from __future__ import annotations

from pathlib import Path

from flask import Blueprint, flash, g, redirect, request, send_file, url_for

from clinic_app.services.i18n import T, get_lang
from clinic_app.services.receipts import (
    ReceiptError,
    get_receipt_metadata,
    issue_receipt,
    recent_receipts,
    reprint_receipt,
)
from clinic_app.services.security import require_permission
from clinic_app.services.ui import render_page
from clinic_app.services.errors import record_exception

bp = Blueprint("receipts", __name__)


@bp.route("/receipts", methods=["GET"], endpoint="index")
@require_permission("receipts:view")
def receipts_list():
    try:
        try:
            receipts = recent_receipts()
        except ReceiptError as exc:
            flash(T(str(exc)), "err")
            receipts = []
        return render_page(
            "receipts/index.html",
            receipts=receipts,
            show_back=True,
        )
    except Exception as exc:  # pragma: no cover
        record_exception("receipts.index", exc)
        raise


@bp.route("/receipts/new", methods=["GET", "POST"], endpoint="new")
@require_permission("receipts:issue")
def new_receipt():
    try:
        defaults = {"locale": get_lang()}
        if request.method == "POST":
            locale = (request.form.get("locale") or get_lang()).lower()
            actor = getattr(g, "current_user", None)
            try:
                issue_receipt(request.form.to_dict(), actor_id=getattr(actor, "id", None), locale=locale)
                flash(T("receipts_success"), "ok")
                return redirect(url_for("receipts.index"))
            except ReceiptError as exc:
                flash(T(str(exc)), "err")
            defaults = request.form.to_dict()
        return render_page(
            "receipts/new.html",
            defaults=defaults,
            show_back=True,
        )
    except Exception as exc:  # pragma: no cover
        record_exception("receipts.new", exc)
        raise


@bp.route("/receipts/<rid>/pdf", methods=["GET"], endpoint="pdf")
@require_permission("receipts:view")
def download_receipt(rid):
    try:
        try:
            meta = get_receipt_metadata(rid)
        except ReceiptError as exc:
            flash(T(str(exc)), "err")
            return redirect(url_for("receipts.index"))
        pdf_path = Path(meta["pdf_path"])
        if not pdf_path.exists():
            flash(T("receipt_not_found"), "err")
            return redirect(url_for("receipts.index"))
        return send_file(pdf_path, mimetype="application/pdf", download_name=f"{meta['number']}.pdf")
    except Exception as exc:  # pragma: no cover
        record_exception("receipts.pdf", exc)
        raise


@bp.route("/receipts/<rid>/reprint", methods=["POST"], endpoint="reprint")
@require_permission("receipts:reprint")
def reprint_receipt_view(rid):
    try:
        actor = getattr(g, "current_user", None)
        try:
            reprint_receipt(rid, actor_id=getattr(actor, "id", None))
            flash(T("receipts_reprint_done"), "ok")
        except ReceiptError as exc:
            flash(T(str(exc)), "err")
        return redirect(request.form.get("next") or url_for("receipts.index"))
    except Exception as exc:  # pragma: no cover
        record_exception("receipts.reprint", exc)
        raise
