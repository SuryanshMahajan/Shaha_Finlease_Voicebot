import jwt

TEST_SECRET = "unit-test-secret-that-is-at-least-32-characters-long"


def admin_headers(role="admin"):
    token = jwt.encode({"sub": "test-admin", "role": role}, TEST_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}
