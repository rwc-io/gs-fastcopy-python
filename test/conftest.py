from unittest import mock
import google.auth
import google.auth.credentials
import pytest


@pytest.fixture(autouse=True)
def mock_google_auth(monkeypatch):
    patched_auth = monkeypatch

    def mock_default(*args, **kwargs):
        creds = mock.create_autospec(google.auth.credentials.Credentials)
        creds.universe_domain = "googleapis.com"
        return creds, "dummy-project"

    patched_auth.setattr(google.auth, "default", mock_default)
