
def test_patient_search_func_import_error(logged_in_client):
    """
    Test that the patient search API endpoint works correctly.
    This test is expected to fail if 'func' is not imported in appointments/routes.py.
    """
    # The search query doesn't matter much, just needs to trigger the query construction
    response = logged_in_client.get("/api/patients/search?q=test")

    # If the bug exists (NameError: name 'func' is not defined), this will likely be 500
    assert response.status_code == 200
    assert response.is_json
