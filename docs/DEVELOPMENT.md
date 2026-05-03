# Development Guide

## Prerequisites

- Python 3.12 or compatible Python 3.x runtime.
- Node.js and npm.
- Docker Desktop or Docker Engine.
- PostgreSQL, MongoDB, and Redis are provided by Docker Compose for local development.

## Local Setup

Start infrastructure:

```bash
docker-compose up -d
```

Create backend environment values as described in [ENVIRONMENT.md](ENVIRONMENT.md).

Install backend dependencies:

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Apply migrations from the repository root or backend folder:

```bash
cd backend
alembic upgrade head
```

Run the backend from the repository root:

```bash
uvicorn backend.main:app --reload
```

Run Celery worker and scheduler from the repository root:

```bash
celery -A backend.config.celery_app worker --loglevel=info
celery -A backend.config.celery_app beat --loglevel=info
```

Install and run the frontend:

```bash
cd frontend
npm install
npm run dev
```

## Backend Development Notes

Use this structure for new backend behavior:

1. Add or update Pydantic schemas in `backend/controllers/schemas.py`.
2. Add persistence changes in `backend/models/`.
3. Add business logic in `backend/services/`.
4. Add HTTP endpoints in `backend/routes/`.
5. Register new routers in `backend/main.py`.
6. Add or update tests in `backend/tests/`.
7. Add Alembic migrations for SQL schema changes.

Generate a migration:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```bash
alembic upgrade head
```

Rollback one migration:

```bash
alembic downgrade -1
```

## Frontend Development Notes

Routes live in `frontend/src/App.jsx`.

Existing pages:

- `/login`
- `/signup`
- `/dashboard`
- `/keys`
- `/billing`
- `/logs`

API access is centralized in `frontend/src/services/axios.js`. Add new endpoint wrappers there so pages do not duplicate URL and token handling logic.

Auth state lives in `frontend/src/store/authStore.js`.

## Seeding Demo Data

The repository includes:

```text
backend/scripts/seed_demo_dashboard.py
```

Use it when you need example dashboard data. Review the script before running so its assumptions match your local database state.

## Troubleshooting

### Backend import errors

If `uvicorn main:app --reload` fails because imports use `backend.*`, run Uvicorn from the repository root:

```bash
uvicorn backend.main:app --reload
```

### Database connection errors

Check that Docker services are running:

```bash
docker-compose ps
```

Then verify that `POSTGRES_URL`, `MONGODB_URL`, and `REDIS_URL` match the local compose ports and passwords.

### Frontend API requests go to the wrong URL

Set `frontend/.env.local`:

```env
VITE_API_URL=http://localhost:8000/api/v1
```

Restart `npm run dev` after changing Vite environment variables.

### Celery cannot find the app

Run Celery from the repository root:

```bash
celery -A backend.config.celery_app worker --loglevel=info
```
