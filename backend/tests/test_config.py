"""Tests for settings loading.

Both behaviours here came from a real mistake: the documented command was run from
`backend/`, so the file landed next to the code rather than at the project root, and it
still contained the example value. Either alone is enough to make a feature silently do
nothing.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def write_env(path, **values):
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")


class TestPlaceholderKeys:
    """Example text left in place must count as "not configured"."""

    @pytest.mark.parametrize(
        "value", ["votre_cle", "your_key", "CHANGEME", "  xxx  ", "", "   "]
    )
    def test_placeholder_is_treated_as_unset(self, value, monkeypatch):
        monkeypatch.setenv("TWELVEDATA_API_KEY", value)

        # A placeholder forwarded to a provider yields an opaque 401 mid-refresh —
        # much harder to diagnose than the feature staying off.
        assert Settings().twelvedata_api_key is None

    def test_a_real_key_is_kept(self, monkeypatch):
        monkeypatch.setenv("TWELVEDATA_API_KEY", "ab12cd34ef56")

        assert Settings().twelvedata_api_key == "ab12cd34ef56"

    def test_surrounding_whitespace_is_trimmed(self, monkeypatch):
        monkeypatch.setenv("TWELVEDATA_API_KEY", "  ab12cd34  ")

        assert Settings().twelvedata_api_key == "ab12cd34"

    def test_the_rule_covers_every_credential(self, monkeypatch):
        for name in ("FINNHUB_API_KEY", "PERPLEXITY_API_KEY", "SEC_USER_AGENT"):
            monkeypatch.setenv(name, "changeme")

        settings = Settings()

        assert settings.finnhub_enabled is False
        assert settings.perplexity_enabled is False
        assert settings.edgar_enabled is False


class TestEnvFileLocations:
    """Running commands from backend/ is natural, so .env is accepted there too."""

    def test_env_file_in_the_backend_directory_is_read(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        write_env(env_file, TWELVEDATA_API_KEY="from_backend_dir")

        assert Settings(_env_file=env_file).twelvedata_api_key == "from_backend_dir"

    def test_project_root_wins_when_both_exist(self, tmp_path, monkeypatch):
        backend_env = tmp_path / "backend.env"
        root_env = tmp_path / "root.env"
        write_env(backend_env, TWELVEDATA_API_KEY="from_backend")
        write_env(root_env, TWELVEDATA_API_KEY="from_root")

        # The root is the documented location, so it must take precedence over a copy
        # left behind in backend/.
        settings = Settings(_env_file=(backend_env, root_env))

        assert settings.twelvedata_api_key == "from_root"
