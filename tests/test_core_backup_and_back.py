def test_backup_route_basic(logged_in_client):
    r = logged_in_client.get("/backup", follow_redirects=True)
    assert r.status_code == 404


def test_add_payment_get_form(logged_in_client):
    r = logged_in_client.get("/payments/new")
    assert r.status_code in (200, 302)


def test_back_route_redirects(logged_in_client):
    r = logged_in_client.get("/back", follow_redirects=False)
    assert r.status_code in (302, 308)
