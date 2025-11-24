"""Expense receipt file handling service for upload, storage, and preview functionality."""

from __future__ import annotations

import os
import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List
from werkzeug.utils import secure_filename

from flask import current_app
from clinic_app.services.database import db


class ExpenseReceiptFileError(Exception):
    """Base exception for expense receipt file operations."""


class InvalidFileError(ExpenseReceiptFileError):
    """Raised when file validation fails."""


class FileTooLargeError(ExpenseReceiptFileError):
    """Raised when file size exceeds limits."""


class UnsupportedFileTypeError(ExpenseReceiptFileError):
    """Raised when file type is not supported."""


class ReceiptFileManager:
    """Manages expense receipt file uploads, storage, and retrieval."""
    
    # Supported file extensions
    ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
    
    # Maximum file size (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    def __init__(self):
        """Initialize the file manager with base directory."""
        self.base_dir = self._get_base_directory()
        self.uploads_dir = self.base_dir / "uploads"
        self.thumbnails_dir = self.base_dir / "thumbnails" 
        self.temp_dir = self.base_dir / "temp"
        
        # Ensure directories exist
        self._ensure_directories()
    
    def _get_base_directory(self) -> Path:
        """Get the base directory for expense receipt files."""
        data_root = Path(current_app.config.get("DATA_ROOT", "data"))
        return data_root / "expense_receipts"
    
    def _ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        directories = [self.base_dir, self.uploads_dir, self.thumbnails_dir, self.temp_dir]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def validate_file(self, file) -> Tuple[bool, str]:
        """Validate uploaded file."""
        if not file or not file.filename:
            return False, "No file selected"
        
        # Check file extension
        if not self._is_allowed_file(file.filename):
            return False, f"File type not supported. Allowed types: {', '.join(self.ALLOWED_EXTENSIONS)}"
        
        # Check file size
        file.seek(0, 2)  # Seek to end
        file_size = file.tell()
        file.seek(0)  # Reset to beginning
        
        if file_size > self.MAX_FILE_SIZE:
            return False, f"File too large. Maximum size: {self.MAX_FILE_SIZE // (1024*1024)}MB"
        
        return True, ""
    
    def _is_allowed_file(self, filename: str) -> bool:
        """Check if file extension is allowed."""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS
    
    def generate_unique_filename(self, original_filename: str, receipt_id: str) -> str:
        """Generate a unique filename for storage."""
        extension = Path(original_filename).suffix.lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_hash = hashlib.md5(f"{receipt_id}_{timestamp}".encode()).hexdigest()[:8]
        return f"{receipt_id}_{timestamp}_{file_hash}{extension}"
    
    def save_uploaded_file(self, file, receipt_id: str) -> str:
        """Save uploaded file and return the stored filename."""
        is_valid, error_msg = self.validate_file(file)
        if not is_valid:
            raise InvalidFileError(error_msg)
        
        # Generate unique filename
        filename = self.generate_unique_filename(file.filename, receipt_id)
        filepath = self.uploads_dir / filename
        
        # Save file
        file.save(str(filepath))
        
        return filename
    
    def get_file_path(self, filename: str) -> Optional[Path]:
        """Get full path for a stored file."""
        if not filename:
            return None
        
        filepath = self.uploads_dir / filename
        return filepath if filepath.exists() else None
    
    def get_file_url(self, filename: str) -> Optional[str]:
        """Get URL for accessing a stored file."""
        if not filename:
            return None
        
        return f"/expense-receipts/files/{filename}"
    
    def delete_file(self, filename: str) -> bool:
        """Delete a stored file."""
        filepath = self.get_file_path(filename)
        if filepath and filepath.exists():
            try:
                filepath.unlink()
                return True
            except OSError:
                return False
        return False
    
    def get_file_info(self, filename: str) -> dict:
        """Get file information."""
        filepath = self.get_file_path(filename)
        if not filepath or not filepath.exists():
            return {}
        
        stat = filepath.stat()
        return {
            'filename': filename,
            'size': stat.st_size,
            'size_mb': round(stat.st_size / (1024*1024), 2),
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'mime_type': mimetypes.guess_type(str(filepath))[0],
            'extension': filepath.suffix.lower()
        }
    
    def create_thumbnail(self, filename: str, max_size: Tuple[int, int] = (200, 200)) -> bool:
        """Create thumbnail for image files (placeholder for future enhancement)."""
        # Placeholder - can be enhanced with PIL for actual thumbnail creation
        return True
    
    def cleanup_temp_files(self, older_than_hours: int = 24) -> int:
        """Clean up temporary files older than specified hours."""
        cutoff_time = datetime.now().timestamp() - (older_than_hours * 3600)
        cleaned_count = 0
        
        for filepath in self.temp_dir.glob("*"):
            if filepath.is_file() and filepath.stat().st_mtime < cutoff_time:
                try:
                    filepath.unlink()
                    cleaned_count += 1
                except OSError:
                    pass
        
        return cleaned_count


# Global instance
_receipt_file_manager = None


def get_receipt_file_manager() -> ReceiptFileManager:
    """Get the global receipt file manager instance."""
    global _receipt_file_manager
    if _receipt_file_manager is None:
        _receipt_file_manager = ReceiptFileManager()
    return _receipt_file_manager