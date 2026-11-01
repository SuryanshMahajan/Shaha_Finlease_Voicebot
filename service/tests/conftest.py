import os

import pytest
from pwdlib import PasswordHash

_TEST_ENV = {
    "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
    "ADMIN_USERNAME": "test-admin",
    "ADMIN_PASSWORD_HASH": PasswordHash.recommended().hash("test-only-password"),
    "JWT_SECRET": "unit-test-secret-that-is-at-least-32-characters-long",
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

from app.core.config import get_settings  # noqa: E402
get_settings.cache_clear()

from app.core.security import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()
