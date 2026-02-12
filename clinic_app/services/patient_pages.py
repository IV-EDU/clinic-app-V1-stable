"""Patient page number management service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from clinic_app.services.database import db


class PatientPageService:
    """Service for managing patient page numbers."""

    @staticmethod
    def _table_exists(conn, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None
    
    @staticmethod
    def add_page_to_patient(patient_id: str, page_number: str, notebook_name: str = None) -> str:
        """Add a page number to a patient."""
        conn = db()
        page_id = str(uuid.uuid4())
        
        try:
            conn.execute(
                """
                INSERT INTO patient_pages (id, patient_id, page_number, notebook_name)
                VALUES (?, ?, ?, ?)
                """,
                (page_id, patient_id, page_number.strip(), notebook_name)
            )
            conn.commit()
            return page_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    @staticmethod
    def remove_page_from_patient(patient_id: str, page_number: str) -> bool:
        """Remove a page number from a patient."""
        conn = db()
        try:
            cursor = conn.execute(
                """
                DELETE FROM patient_pages 
                WHERE patient_id = ? AND page_number = ?
                """,
                (patient_id, page_number.strip())
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    @staticmethod
    def get_patient_pages(patient_id: str) -> List[Dict[str, Any]]:
        """Get all page numbers for a patient."""
        conn = db()
        try:
            has_notebooks = PatientPageService._table_exists(conn, "notebooks")
            if has_notebooks:
                rows = conn.execute(
                    """
                    SELECT pg.id, pg.page_number, pg.notebook_name, pg.created_at, pg.updated_at,
                           nb.color AS notebook_color
                      FROM patient_pages pg
                      LEFT JOIN notebooks nb
                        ON lower(trim(nb.name)) = lower(trim(pg.notebook_name))
                     WHERE pg.patient_id = ?
                     ORDER BY pg.page_number
                    """,
                    (patient_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, page_number, notebook_name, created_at, updated_at, NULL AS notebook_color
                    FROM patient_pages
                    WHERE patient_id = ?
                    ORDER BY page_number
                    """,
                    (patient_id,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    
    @staticmethod
    def search_patients_by_page(query: str) -> List[Dict[str, Any]]:
        """Search patients by page number."""
        from clinic_app.services.patients import normalize_arabic
        conn = db()
        try:
            norm_query = normalize_arabic(query.strip().lower())
            search_term = f"%{norm_query}%"

            # For non-arabic fields or when normalization isn't needed
            raw_search_term = f"%{query.strip().lower()}%"

            digits = "".join(ch for ch in str(query or "") if ch.isdigit())
            search_digits = f"%{digits}%" if digits else ""
            has_patient_phones = PatientPageService._table_exists(conn, "patient_phones")
            if has_patient_phones:
                if digits:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT p.id, p.short_id, p.full_name, p.phone,
                               GROUP_CONCAT(DISTINCT pg.page_number) as page_numbers
                          FROM patients p
                          LEFT JOIN patient_pages pg ON p.id = pg.patient_id
                     WHERE LOWER(pg.page_number) LIKE ?
                        OR (NORMALIZE_ARABIC(pg.notebook_name) LIKE ? AND pg.notebook_name NOT LIKE 'pc:%')
                        OR LOWER(p.short_id) LIKE ?
                        OR NORMALIZE_ARABIC(p.full_name) LIKE ?
                        OR LOWER(p.phone) LIKE ?
                            OR replace(replace(replace(replace(replace(p.phone,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?
                            OR EXISTS (
                                SELECT 1
                                  FROM patient_phones ph
                                 WHERE ph.patient_id = p.id
                                   AND (
                                        LOWER(ph.phone) LIKE ?
                                        OR LOWER(ph.phone_normalized) LIKE ?
                                        OR replace(replace(replace(replace(replace(ph.phone,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?
                                        OR replace(replace(replace(replace(replace(ph.phone_normalized,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?
                                   )
                            )
                         GROUP BY p.id
                         ORDER BY p.full_name
                         LIMIT 10
                        """,
                        (
                            raw_search_term,
                            search_term,
                            raw_search_term,
                            search_term,
                            raw_search_term,
                            search_digits,
                            raw_search_term,
                            search_digits,
                            search_digits,
                            search_digits,
                        ),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT p.id, p.short_id, p.full_name, p.phone,
                               GROUP_CONCAT(DISTINCT pg.page_number) as page_numbers
                          FROM patients p
                          LEFT JOIN patient_pages pg ON p.id = pg.patient_id
                     WHERE LOWER(pg.page_number) LIKE ?
                       OR (NORMALIZE_ARABIC(pg.notebook_name) LIKE ? AND pg.notebook_name NOT LIKE 'pc:%')
                       OR LOWER(p.short_id) LIKE ?
                       OR NORMALIZE_ARABIC(p.full_name) LIKE ?
                       OR LOWER(p.phone) LIKE ?
                            OR EXISTS (
                                SELECT 1
                                  FROM patient_phones ph
                                 WHERE ph.patient_id = p.id
                                   AND (LOWER(ph.phone) LIKE ?)
                            )
                         GROUP BY p.id
                         ORDER BY p.full_name
                         LIMIT 10
                        """,
                        (
                            raw_search_term,
                            search_term,
                            raw_search_term,
                            search_term,
                            raw_search_term,
                            raw_search_term,
                        ),
                    ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DISTINCT p.id, p.short_id, p.full_name, p.phone, 
                           GROUP_CONCAT(pg.page_number) as page_numbers
                    FROM patients p
                    LEFT JOIN patient_pages pg ON p.id = pg.patient_id
                    WHERE LOWER(pg.page_number) LIKE ?
                       OR NORMALIZE_ARABIC(pg.notebook_name) LIKE ?
                       OR LOWER(p.short_id) LIKE ?
                       OR NORMALIZE_ARABIC(p.full_name) LIKE ?
                       OR LOWER(p.phone) LIKE ?
                    GROUP BY p.id
                    ORDER BY p.full_name
                    LIMIT 10
                    """,
                    (raw_search_term, search_term, raw_search_term, search_term, raw_search_term),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
    
    @staticmethod
    def get_page_statistics() -> Dict[str, Any]:
        """Get statistics about page numbers."""
        conn = db()
        try:
            stats = conn.execute(
                """
                SELECT 
                    COUNT(*) as total_pages,
                    COUNT(DISTINCT patient_id) as patients_with_pages,
                    COUNT(DISTINCT notebook_name) as total_notebooks
                FROM patient_pages
                WHERE notebook_name IS NOT NULL
                """
            ).fetchone()
            
            # Most common page numbers
            common_pages = conn.execute(
                """
                SELECT page_number, COUNT(*) as usage_count
                FROM patient_pages
                GROUP BY page_number
                ORDER BY usage_count DESC
                LIMIT 5
                """
            ).fetchall()
            
            return {
                "total_pages": stats["total_pages"] or 0,
                "patients_with_pages": stats["patients_with_pages"] or 0,
                "total_notebooks": stats["total_notebooks"] or 0,
                "common_pages": [dict(row) for row in common_pages]
            }
        finally:
            conn.close()


class AdminSettingsService:
    """Service for managing admin settings."""
    
    @staticmethod
    def get_setting(key: str, default_value: str = None) -> str:
        """Get a raw setting value as a string (legacy helper)."""
        conn = db()
        try:
            row = conn.execute(
                """
                SELECT setting_value FROM admin_settings WHERE setting_key = ?
                """,
                (key,)
            ).fetchone()
            return row["setting_value"] if row else default_value
        finally:
            conn.close()
    
    @staticmethod
    def set_setting(key: str, value: str, setting_type: str = "string") -> bool:
        """Set a setting value (stored as text plus a simple type)."""
        conn = db()
        try:
            now = datetime.now().isoformat()
            existing = conn.execute(
                "SELECT id FROM admin_settings WHERE setting_key = ?",
                (key,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE admin_settings
                       SET setting_value = ?, setting_type = ?, updated_at = ?
                     WHERE setting_key = ?
                    """,
                    (value, setting_type, now, key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO admin_settings
                        (id, setting_key, setting_value, setting_type, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), key, value, setting_type, now),
                )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    @staticmethod
    def get_all_settings() -> Dict[str, Any]:
        """Get all admin settings as a simple key → value mapping.

        Values are decoded based on their setting_type:
          - 'boolean' → bool
          - 'int'     → int when possible
          - everything else → raw string
        """
        conn = db()
        try:
            rows = conn.execute(
                """
                SELECT setting_key, setting_value, setting_type, description
                FROM admin_settings
                ORDER BY setting_key
                """
            ).fetchall()
            
            settings = {}
            for row in rows:
                key = row["setting_key"]
                raw = row["setting_value"]
                typ = (row["setting_type"] or "string").lower()
                if typ == "boolean":
                    val: Any = str(raw).lower() == "true"
                elif typ == "int":
                    try:
                        val = int(raw)
                    except (TypeError, ValueError):
                        val = raw
                else:
                    val = raw
                settings[key] = val
            return settings
        finally:
            conn.close()
    
    @staticmethod
    def update_settings(settings: Dict[str, Any]) -> None:
        """Update multiple settings in one call.

        The caller decides which keys to pass; types are inferred from the
        Python values (bool → 'boolean', int → 'int', otherwise 'string').
        """
        conn = db()
        try:
            now = datetime.now().isoformat()
            for key, value in settings.items():
                if key in (None, ""):
                    continue
                if isinstance(value, bool):
                    v_str = "true" if value else "false"
                    v_type = "boolean"
                elif isinstance(value, int):
                    v_str = str(value)
                    v_type = "int"
                else:
                    v_str = str(value)
                    v_type = "string"
                existing = conn.execute(
                    "SELECT id FROM admin_settings WHERE setting_key = ?",
                    (key,),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE admin_settings
                           SET setting_value = ?, setting_type = ?, updated_at = ?
                         WHERE setting_key = ?
                        """,
                        (v_str, v_type, now, key),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO admin_settings
                            (id, setting_key, setting_value, setting_type, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (str(uuid.uuid4()), key, v_str, v_type, now),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    @staticmethod
    def is_file_number_enabled() -> bool:
        """Check if file numbers are enabled."""
        return AdminSettingsService.get_setting("enable_file_numbers", "false").lower() == "true"
    
    @staticmethod
    def get_page_number_mode() -> str:
        """Get the page number entry mode."""
        return AdminSettingsService.get_setting("page_number_mode", "manual")
    
    @staticmethod
    def get_default_notebook_name() -> str:
        """Get the default notebook name."""
        return AdminSettingsService.get_setting("default_notebook_name", "Main Notebook")

    @staticmethod
    def get_notebooks() -> List[Dict[str, Any]]:
        """Get manually defined notebook names/colors (optional feature)."""
        conn = db()
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='notebooks' LIMIT 1"
            ).fetchone()
            if not exists:
                return []
            rows = conn.execute(
                """
                SELECT id, name, color, active
                  FROM notebooks
                 WHERE COALESCE(active, 1) = 1
                 ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


class ExcelImportService:
    """Service for handling Excel import with page numbers."""
    
    @staticmethod
    def parse_patient_data(row_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse patient data from Excel row."""
        patient_data = {
            "short_id": row_data.get("short_id", "").strip(),
            "full_name": row_data.get("full_name", "").strip(),
            "phone": row_data.get("phone", "").strip(),
            "notes": row_data.get("notes", "").strip(),
            "page_numbers": []
        }
        
        # Extract page numbers from various possible columns
        page_sources = [
            row_data.get("page_number", ""),
            row_data.get("page_numbers", ""),
            row_data.get("notebook_page", ""),
            row_data.get("physical_page", "")
        ]
        
        for source in page_sources:
            if source:
                # Split by common delimiters
                pages = [p.strip() for p in str(source).replace(",", "|").replace(";", "|").split("|") if p.strip()]
                patient_data["page_numbers"].extend(pages)
        
        # Remove duplicates while preserving order
        patient_data["page_numbers"] = list(dict.fromkeys(patient_data["page_numbers"]))
        
        return patient_data
    
    @staticmethod
    def import_patient_with_pages(patient_data: Dict[str, Any]) -> str:
        """Import a patient with page numbers."""
        conn = db()
        try:
            # Create or update patient
            patient_id = str(uuid.uuid4())
            
            # Check if patient already exists by name or phone
            existing = conn.execute(
                """
                SELECT id FROM patients 
                WHERE LOWER(TRIM(full_name)) = LOWER(TRIM(?))
                   OR (phone IS NOT NULL AND phone = ?)
                   OR (short_id IS NOT NULL AND short_id = ?)
                LIMIT 1
                """,
                (patient_data["full_name"], patient_data["phone"], patient_data["short_id"])
            ).fetchone()
            
            if existing:
                patient_id = existing["id"]
                # Update existing patient
                conn.execute(
                    """
                    UPDATE patients 
                    SET short_id = COALESCE(?, short_id),
                        full_name = COALESCE(?, full_name),
                        phone = COALESCE(?, phone),
                        notes = COALESCE(?, notes),
                        primary_page_number = COALESCE(?, primary_page_number)
                    WHERE id = ?
                    """,
                    (
                        patient_data["short_id"] or None,
                        patient_data["full_name"],
                        patient_data["phone"] or None,
                        patient_data["notes"] or None,
                        patient_data["page_numbers"][0] if patient_data["page_numbers"] else None,
                        patient_id
                    )
                )
            else:
                # Create new patient
                conn.execute(
                    """
                    INSERT INTO patients (id, short_id, full_name, phone, notes, primary_page_number)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        patient_id,
                        patient_data["short_id"] or None,
                        patient_data["full_name"],
                        patient_data["phone"] or None,
                        patient_data["notes"] or None,
                        patient_data["page_numbers"][0] if patient_data["page_numbers"] else None
                    )
                )
            
            # Add page numbers
            for page_number in patient_data["page_numbers"]:
                if page_number:
                    try:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO patient_pages (id, patient_id, page_number)
                            VALUES (?, ?, ?)
                            """,
                            (str(uuid.uuid4()), patient_id, page_number)
                        )
                    except Exception:
                        # Skip duplicate page numbers
                        continue
            
            conn.commit()
            return patient_id
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
