def test_add_payment_get_form_no_500(logged_in_client):
    r = logged_in_client.get("/payments/new")
    assert r.status_code < 500, f"/payments/new returned {r.status_code}"
