"""WSGI entry that exposes the configured Flask application."""

from __future__ import annotations

from . import APP_HOST, APP_PORT, create_app


app = create_app()


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=False)
