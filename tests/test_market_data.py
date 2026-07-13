from backend.market_data import apply_metadata_overrides


def test_metadata_override_corrects_inception_date():
    metadata = {"inception_date": "2000-01-01", "full_name": "Test Fund"}

    corrected = apply_metadata_overrides("PBAIX", metadata)

    assert corrected["inception_date"] == "1993-06-01"
    assert corrected["full_name"] == "Test Fund"
