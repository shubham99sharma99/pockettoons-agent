"""MotherDuck mode is chosen only when both the token and the database name are set."""
from agent import db


def test_local_by_default(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.delenv("PT_MD_DATABASE", raising=False)
    assert db.motherduck_database() is None
    assert db.target() == str(db.db_path())


def test_needs_both_token_and_name(monkeypatch):
    monkeypatch.setenv("PT_MD_DATABASE", "pockettoons")
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    assert db.motherduck_database() is None
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "x")
    assert db.motherduck_database() == "pockettoons"
    assert db.target() == "md:pockettoons"
    assert "x" not in db.target()
