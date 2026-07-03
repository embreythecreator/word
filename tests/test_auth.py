from api.auth import _is_valid_bearer_token, get_api_bearer_tokens, is_auth_enabled


def test_ward_token_enables_bearer_auth(monkeypatch):
    monkeypatch.delenv("OPEN_NOTEBOOK_PASSWORD", raising=False)
    monkeypatch.setenv("OPEN_NOTEBOOK_WARD_TOKEN", "ward-secret")

    assert is_auth_enabled() is True
    assert get_api_bearer_tokens() == ["ward-secret"]
    assert _is_valid_bearer_token("ward-secret") is True
    assert _is_valid_bearer_token("wrong") is False


def test_auth_disabled_without_configured_tokens(monkeypatch):
    for env_name in (
        "OPEN_NOTEBOOK_WARD_TOKEN",
        "WARD_TOKEN",
        "API_SERVER_KEY",
        "OPEN_NOTEBOOK_PASSWORD",
    ):
        monkeypatch.delenv(env_name, raising=False)

    assert is_auth_enabled() is False
    assert get_api_bearer_tokens() == []
