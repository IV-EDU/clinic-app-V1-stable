from urllib.parse import urlparse

from clinic_app.services.i18n import get_lang


def test_locale_cookie_priority(app):
    cookie_name = app.config["LOCALE_COOKIE_NAME"]
    headers = [("Cookie", f"{cookie_name}=ar")]
    with app.test_request_context("/?lang=en", headers=headers):
        assert get_lang() == "ar"


def test_locale_query_selected_when_no_cookie(app):
    with app.test_request_context("/?lang=ar"):
        assert get_lang() == "ar"


def test_locale_falls_back_to_config_default(app):
    app.config["DEFAULT_LOCALE"] = "ar"
    with app.test_request_context("/"):
        assert get_lang() == "ar"


def test_set_lang_sets_cookie_and_redirects(client, get_csrf_token):
    page = client.get("/auth/login")
    token = get_csrf_token(page)
    resp = client.post(
        "/lang",
        data={"lang": "ar", "next": "/patients", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert urlparse(resp.headers["Location"]).path == "/patients"
    cookie_header = resp.headers.get("Set-Cookie", "")
    assert f"{client.application.config['LOCALE_COOKIE_NAME']}=ar" in cookie_header


def test_set_lang_blocks_external_redirects_and_invalid_lang(client, get_csrf_token):
    page = client.get("/auth/login")
    token = get_csrf_token(page)
    resp = client.post(
        "/lang",
        data={
            "lang": "zz",
            "next": "https://example.com/malware",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert urlparse(resp.headers["Location"]).path == "/"
    cookie_header = resp.headers.get("Set-Cookie", "")
    assert f"{client.application.config['LOCALE_COOKIE_NAME']}=en" in cookie_header
