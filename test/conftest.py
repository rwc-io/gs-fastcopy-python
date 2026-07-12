from unittest import mock
import google.auth
import google.auth.credentials
import pytest


@pytest.fixture(autouse=True)
def mock_google_auth():
    def mock_default(*args, **kwargs):
        creds = mock.create_autospec(google.auth.credentials.Credentials)
        creds.universe_domain = "googleapis.com"
        return creds, "dummy-project"

    with mock.patch("google.auth.default", side_effect=mock_default):
        yield
