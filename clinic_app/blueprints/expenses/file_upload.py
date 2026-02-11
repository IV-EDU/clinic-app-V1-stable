"""File upload routes for expense receipts."""

from __future__ import annotations

import json
from flask import request, jsonify, current_app, send_file
from flask_login import current_user
from werkzeug.utils import secure_filename

from clinic_app.services.expense_receipt_files import (
    get_receipt_file_manager, 
    InvalidFileError, 
    FileTooLargeError, 
    UnsupportedFileTypeError
)
from clinic_app.services.security import require_permission

# Import the existing expenses blueprint
from clinic_app.blueprints.expenses.routes import bp


@bp.route("/api/expenses/upload", methods=["POST"])
@require_permission("expenses:edit")
def upload_receipt_file():
    """Handle file upload for expense receipts."""
    try:
        file_manager = get_receipt_file_manager()
        
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["file"]
        receipt_id = request.form.get("receipt_id", "")
        
        if not receipt_id:
            return jsonify({"error": "Receipt ID is required"}), 400
        
        # Validate and save file
        try:
            filename = file_manager.save_uploaded_file(file, receipt_id)
        except InvalidFileError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": "Failed to save file"}), 500
        
        # Get file info
        file_info = file_manager.get_file_info(filename)
        file_url = file_manager.get_file_url(filename)
        
        return jsonify({
            "success": True,
            "filename": filename,
            "url": file_url,
            "file_info": file_info
        })
        
    except Exception as e:
        return jsonify({"error": "Upload failed"}), 500


@bp.route("/expense-receipts/files/<filename>")
@require_permission("expenses:view")
def serve_receipt_file(filename):
    """Serve uploaded receipt files."""
    try:
        file_manager = get_receipt_file_manager()
        filepath = file_manager.get_file_path(filename)
        
        if not filepath or not filepath.exists():
            return "File not found", 404
        
        return send_file(str(filepath))
        
    except Exception as e:
        return "Error serving file", 500


@bp.route("/api/expenses/files/<receipt_id>", methods=["GET"])
@require_permission("expenses:view")
def get_receipt_files(receipt_id):
    """Get files associated with a receipt."""
    try:
        # This would be enhanced to query the database for file associations
        # For now, return empty list as placeholder
        return jsonify({"files": []})
        
    except Exception as e:
        return jsonify({"error": "Failed to get files"}), 500


@bp.route("/api/expenses/files/<receipt_id>", methods=["DELETE"])
@require_permission("expenses:edit")
def delete_receipt_file(receipt_id):
    """Delete a file associated with a receipt."""
    try:
        filename = request.json.get("filename")
        if not filename:
            return jsonify({"error": "Filename is required"}), 400
        
        file_manager = get_receipt_file_manager()
        success = file_manager.delete_file(filename)
        
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "File not found"}), 404
            
    except Exception as e:
        return jsonify({"error": "Delete failed"}), 500