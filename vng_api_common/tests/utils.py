def get_validation_errors(response, field, index=0):
    """
    Extra the validation error for ``field`` from the response.

    Assumes there's only one validation error for the field.
    """
    assert response.status_code == 400
    i = 0
    for error in response.data["invalid_params"]:
        if error["name"] != field:
            continue

        if i == index:
            return error

        i += 1
