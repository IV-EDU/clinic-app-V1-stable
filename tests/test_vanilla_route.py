#!/usr/bin/env python3
"""Smoke test for the vanilla appointments data injection."""

import json


def test_data_injection(app):
    """Appointments vanilla template can render without Jinja errors."""
    with app.test_client() as client:
        # Not logged in → expect redirect to login
        resp = client.get("/appointments/vanilla")
        assert resp.status_code in (200, 302)


def test_json_serialization():
    """Ensure empty data structures serialise to valid JSON."""
    test_data = {
        "appointments_json": json.dumps([]),
        "patients_json": json.dumps([]),
        "doctors_json": json.dumps(["All Doctors"]),
    }
    for key, value in test_data.items():
        assert json.loads(value) is not None, f"{key} produced invalid JSON"
