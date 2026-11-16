import subprocess

from app import build_info as module


def setup_function():
    module.build_info.cache_clear()


def teardown_function():
    module.build_info.cache_clear()


def test_reads_head_of_the_checkout():
    info = module.build_info()

    assert info["commit"] and len(info["commit"]) >= 7
    assert info["committed_at"] and "T" in info["committed_at"]


def test_environment_overrides_the_commit(monkeypatch):
    monkeypatch.setenv("STOCK_ANALYST_COMMIT", "0123456789abcdef0123")

    assert module.build_info() == {"commit": "0123456789ab", "committed_at": None}


def test_no_git_gives_nothing_rather_than_an_error(monkeypatch):
    monkeypatch.delenv("STOCK_ANALYST_COMMIT", raising=False)

    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", missing)

    assert module.build_info() == {"commit": None, "committed_at": None}


def test_not_a_repository_gives_nothing(monkeypatch):
    monkeypatch.delenv("STOCK_ANALYST_COMMIT", raising=False)

    def fails(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "run", fails)

    assert module.build_info() == {"commit": None, "committed_at": None}
