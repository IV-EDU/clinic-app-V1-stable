def test_wiring_runs_before_first_request(app):
    with app.test_request_context('/'):
        app.preprocess_request()  # runs before_app_request hooks
    # If we reached here, no NameError from lazy wiring
