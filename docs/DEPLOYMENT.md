# Deployment Guide

MeterFlow includes a production Docker Compose file with Nginx, FastAPI, Celery worker, Celery Beat, PostgreSQL, MongoDB, and Redis.

## Production Stack

```text
Internet
  |
  v
Nginx :80/:443
  |
  v
FastAPI backend :8000 internal
  |
  |-- PostgreSQL internal
  |-- MongoDB internal
  |-- Redis internal
  |
  v
Celery worker and Celery Beat
```

## Production Compose

Start:

```bash
docker-compose -f docker-compose.prod.yml up -d --build
```

Stop:

```bash
docker-compose -f docker-compose.prod.yml down
```

View logs:

```bash
docker-compose -f docker-compose.prod.yml logs -f backend
docker-compose -f docker-compose.prod.yml logs -f celery_worker
docker-compose -f docker-compose.prod.yml logs -f nginx
```

## Required Production Preparation

1. Create `backend/.env` with production values.
2. Set strong database, Redis, JWT, Stripe, and SendGrid secrets.
3. Put SSL certificates in `nginx/ssl` or adapt `nginx/nginx.conf` for your certificate strategy.
4. Review exposed ports. Production should expose only Nginx ports `80` and `443`.
5. Run migrations before serving traffic.

## Migrations

Run migrations inside the backend container after the stack is built:

```bash
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

## Health Checks

Check the public health endpoint:

```bash
curl http://localhost/health
```

Expected response includes dependency status:

```json
{
  "status": "healthy",
  "dependencies": {
    "redis": true,
    "mongodb": true,
    "postgresql": true
  }
}
```

`status` can be `degraded` if any dependency check fails.

## Security Checklist

- Use a long random `JWT_SECRET_KEY`.
- Never use development database passwords in production.
- Set `DEBUG=False`.
- Keep PostgreSQL, MongoDB, and Redis off the public internet.
- Configure `STRIPE_WEBHOOK_SECRET` before enabling Stripe webhooks.
- Verify `EMAIL_FROM` with SendGrid.
- Store secrets outside source control.
- Add real domain names and CORS origins before public launch.
- Add monitoring for backend, worker, database, Redis, and queue depth.

## Scaling Notes

- Scale FastAPI horizontally behind Nginx or a load balancer.
- Run multiple Celery workers for higher background task throughput.
- Keep only one Celery Beat scheduler active unless you switch to a distributed scheduler lock.
- Move PostgreSQL, MongoDB, and Redis to managed services for production reliability.
- Watch MongoDB log volume and retention policy as request traffic grows.
