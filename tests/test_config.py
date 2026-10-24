import pytest

from personal_hq.config import ConfigError, load_settings, parse_notion_id

URL = "https://app.notion.com/p/Personal-HQ-401dc3e5c72480eabce6dcd3961cdf79?source=copy_link"
UUID = "401dc3e5-c724-80ea-bce6-dcd3961cdf79"


@pytest.mark.parametrize("value", [URL, "401dc3e5c72480eabce6dcd3961cdf79", UUID, UUID.upper(),
                                   "https://www.notion.so/workspace/Personal-HQ-401dc3e5c72480eabce6dcd3961cdf79"])
def test_parse_notion_id(value):
    assert parse_notion_id(value) == UUID


@pytest.mark.parametrize("value", ["", "https://app.notion.com/p/Personal-HQ", "abc"])
def test_parse_notion_id_rejects_garbage(value):
    with pytest.raises(ConfigError):
        parse_notion_id(value)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_PARENT_PAGE", raising=False)
    return tmp_path / "missing.env"


def test_missing_token_is_reported(clean_env, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE", URL)
    with pytest.raises(ConfigError, match="NOTION_TOKEN"):
        load_settings(env_file=clean_env)


def test_token_not_required_offline(clean_env, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE", URL)
    assert load_settings(require_token=False, env_file=clean_env).parent_page_id == UUID


def test_missing_parent_is_reported(clean_env, monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "ntn_" + "x" * 40)
    with pytest.raises(ConfigError, match="NOTION_PARENT_PAGE"):
        load_settings(env_file=clean_env)


def test_malformed_token(clean_env, monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE", URL)
    monkeypatch.setenv("NOTION_TOKEN", "short")
    with pytest.raises(ConfigError, match="malformed"):
        load_settings(env_file=clean_env)


def test_secret_never_in_repr(clean_env, monkeypatch):
    secret = "ntn_" + "s3cr3t" * 8
    monkeypatch.setenv("NOTION_PARENT_PAGE", URL)
    monkeypatch.setenv("NOTION_TOKEN", secret)
    settings = load_settings(env_file=clean_env)
    assert settings.token == secret
    assert secret not in repr(settings) and secret not in str(settings)


def test_env_file_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_PARENT_PAGE", raising=False)
    env = tmp_path / ".env"
    env.write_text(f"NOTION_TOKEN=ntn_{'a' * 40}\nNOTION_PARENT_PAGE={URL}\n")
    assert load_settings(env_file=env).parent_page_id == UUID
