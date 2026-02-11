def test_audit_payments_endpoint(logged_in_client):
    resp = logged_in_client.get("/admin/settings/audit/payments.json?limit=50")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("success") is True
    assert isinstance(data.get("items"), list)

