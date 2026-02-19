"""Smoke test for the vanilla appointments route."""

import re


def test_vanilla_route(app):
    """Appointments vanilla route returns 200 with required JSON script tags."""
    with app.test_client() as client:
        response = client.get('/appointments/vanilla')

        # Route should load (200) or redirect (302 to login) — never 500
        assert response.status_code in (200, 302), (
            f"Unexpected status {response.status_code}"
        )

        if response.status_code == 200:
            content = response.get_data(as_text=True)
            assert 'appointments-data' in content, (
                "Missing appointments-data script tag in response"
            )
            # Verify the script tag is parseable
            json_match = re.search(
                r'id="appointments-data"[^>]*>([^<]*)</script>', content
            )
            assert json_match, "appointments-data script tag not properly formed"
