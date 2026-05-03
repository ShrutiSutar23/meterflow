# Environment Variables

MeterFlow uses Pydantic settings from `backend/config/settings.py`. Values are loaded from `backend/.env` when the backend runs with the backend directory as the working directory, or from `.env` in the current working directory otherwise.

For fewer surprises, run backend commands from the repository root and set the values in a root `.env`, or run from `backend/` and keep `backend/.env` there. Production Docker Compose expects `./backend/.env`.

## Backend Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `MeterFlow` | Application name |
| `DEBUG` | `False` | Enables debug logging when true |
| `API_VERSION` | `v1` | API version label |
| `POSTGRES_URL` | `postgresql+asyncpg://meterflow_user:password@localhost:5432/meterflow_db` | Async SQLAlchemy PostgreSQL URL |
| `MONGODB_URL` | `mongodb://localhost:27017` | MongoDB connection URL |
| `MONGODB_DB_NAME` | `meterflow_logs` | MongoDB database name |
| `REDIS_URL` | `redis://localhost:6379` | Redis URL for rate limiting and Celery |
| `JWT_SECRET_KEY` | insecure placeholder | Secret used to sign JWTs |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `RATE_LIMIT_PER_MINUTE` | `60` | Default per-minute rate limit |
| `RATE_LIMIT_BURST` | `10` | Burst allowance |
| `FREE_TIER_MONTHLY_REQUESTS` | `10000` | Free monthly included requests |
| `COST_PER_1000_REQUESTS` | `0.50` | Metered cost after free allowance |
| `STRIPE_SECRET_KEY` | empty | Stripe API secret key |
| `STRIPE_WEBHOOK_SECRET` | empty | Stripe webhook signing secret |
| `SENDGRID_API_KEY` | empty | SendGrid API key |
| `EMAIL_FROM` | `noreply@meterflow.io` | Sender email address |

## Local Backend Example

```env
APP_NAME=MeterFlow
DEBUG=True
API_VERSION=v1

POSTGRES_URL=postgresql+asyncpg://meterflow_user:your_password@localhost:5432/meterflow_db
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=meterflow_logs
REDIS_URL=redis://localhost:6379

JWT_SECRET_KEY=replace-this-with-a-long-random-secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10
FREE_TIER_MONTHLY_REQUESTS=10000
COST_PER_1000_REQUESTS=0.50

STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
SENDGRID_API_KEY=
EMAIL_FROM=noreply@meterflow.io
```

Generate a local JWT secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Frontend Variables

Vite variables must begin with `VITE_`.

| Variable | Example | Purpose |
| --- | --- | --- |
| `VITE_API_URL` | `http://localhost:8000/api/v1` | Backend API base URL |

Create `frontend/.env.local`:

```env
VITE_API_URL=http://localhost:8000/api/v1
```

If `VITE_API_URL` is not set, `frontend/src/services/axios.js` defaults to `/api/v1`, which works behind an Nginx or proxy setup.

## Production Notes

- Use strong unique values for database passwords, Redis password, JWT secret, Stripe keys, and SendGrid key.
- Do not commit `.env`, `.env.local`, or real credentials.
- `docker-compose.prod.yml` references additional variables such as `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_DB`, `MONGO_USER`, `MONGO_PASSWORD`, and `REDIS_PASSWORD` for service containers.
- Keep production databases internal; only expose the Nginx ports.
