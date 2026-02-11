from clinic_app import create_app
app = create_app()

if __name__ == "__main__":
    # Fallback host/port; the stable app may override internally
    app.run(host="127.0.0.1", port=8080, debug=False)
