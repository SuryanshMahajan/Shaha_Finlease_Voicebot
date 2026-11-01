import pytest

from app.core.config import Settings


def test_render_postgres_connection_string_uses_pinned_psycopg_driver():
    settings = Settings(database_url="postgresql://render-user:render-pass@private-host:5432/shaha_finlease")
    assert settings.database_url == "postgresql+psycopg://render-user:render-pass@private-host:5432/shaha_finlease"


def test_explicit_psycopg_connection_string_is_preserved():
    value = "postgresql+psycopg://local-user:local-pass@localhost:5432/shaha_finlease"
    assert Settings(database_url=value).database_url == value


def test_non_postgres_connection_strings_are_rejected():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(database_url="sqlite:///not-supported.db")
