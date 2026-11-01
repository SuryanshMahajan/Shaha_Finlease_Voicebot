# Backend

Python 3.11+ FastAPI service. Runtime dependencies are pinned in `requirements.txt`; developer tools are in `requirements-dev.txt`. Configure `DATABASE_URL` and `CORS_ORIGINS` using environment variables. Run from this directory: `uvicorn app.main:app --reload`, then apply schema with `alembic upgrade head`. See [setup](../docs/SETUP.md), [API](../docs/API.md), and [architecture](../docs/ARCHITECTURE.md).

