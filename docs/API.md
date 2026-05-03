# API Reference

Base URL:

```text
http://localhost:8000/api/v1
```

Interactive documentation is available at:

```text
http://localhost:8000/docs
```

Most dashboard endpoints require:

```http
Authorization: Bearer <access_token>
```

## System

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Service metadata |
| `GET` | `/health` | Health check for PostgreSQL, MongoDB, and Redis |

## Authentication

Mounted under `/api/v1/auth`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/signup` | Register a new user |
| `POST` | `/login` | Authenticate and receive tokens |
| `POST` | `/refresh` | Rotate access/refresh tokens |
| `GET` | `/me` | Return the current user |
| `POST` | `/logout` | Logout and invalidate token state where supported |
| `POST` | `/forgot-password` | Start password reset flow |
| `POST` | `/reset-password` | Complete password reset |
| `POST` | `/change-password` | Change password for logged-in user |
| `GET` | `/verify/{token}` | Verify email token |
| `POST` | `/resend-verification` | Send another verification email |

Example login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"you@example.com\",\"password\":\"password123\"}"
```

## API Keys

Mounted under `/api/v1/keys`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/` | Create a new API key |
| `GET` | `/` | List current user's API keys |
| `DELETE` | `/{key_id}` | Revoke an API key |
| `POST` | `/verify` | Verify an API key |

Important behavior:

- The full API key is returned only once from `POST /keys/`.
- The database stores the SHA-256 hash, not the raw key.
- The list endpoint returns metadata and prefix only.

## Users

Mounted under `/api/v1/users`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/me` | Return current user profile |
| `PATCH` | `/me` | Update current user profile |
| `GET` | `/` | List users; role-protected |
| `PATCH` | `/{user_id}/plan` | Update a user's plan; role-protected |

## Billing

Mounted under `/api/v1/billing`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/summary` | Current usage, limits, and projected charges |
| `GET` | `/invoices` | Invoice history |
| `GET` | `/plans` | Available plan information |
| `POST` | `/simulate` | Simulate bill amount for a request count and plan |

## Analytics and Logs

Mounted under `/api/v1`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/analytics/dashboard` | Dashboard summary metrics |
| `GET` | `/analytics/volume` | Request volume over time |
| `GET` | `/analytics/latency` | Latency percentiles |
| `GET` | `/analytics/errors` | Error breakdown |
| `GET` | `/analytics/endpoints` | Endpoint usage ranking |
| `GET` | `/logs` | Paginated request logs |
| `GET` | `/logs/{request_id}` | One request log detail |

Common query parameters are implemented by route/service code, such as `days`, `hours`, and `granularity`.

## Stripe Payments

Mounted under `/api/v1/payments`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/setup-intent` | Create a Stripe setup intent |
| `GET` | `/methods` | List saved payment methods |
| `POST` | `/methods/default` | Set default payment method |
| `DELETE` | `/methods/{payment_method_id}` | Remove payment method |
| `POST` | `/charge` | Charge a customer |
| `POST` | `/refund` | Refund a charge/payment |

Stripe routes require `STRIPE_SECRET_KEY` to be configured.

## Webhooks

Mounted under `/api/v1/webhooks`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/stripe` | Receive inbound Stripe webhook events |
| `POST` | `/register` | Register an outbound webhook URL |
| `POST` | `/test` | Send a test webhook |
| `GET` | `/` | List configured outbound webhooks |
| `DELETE` | `/` | Delete configured outbound webhook |

Inbound Stripe webhook verification uses `STRIPE_WEBHOOK_SECRET`.

## Organizations

Mounted under `/api/v1/orgs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/` | Create an organization |
| `GET` | `/` | List organizations for current user |
| `GET` | `/{slug}` | Get organization detail |
| `PATCH` | `/{slug}` | Update organization |
| `DELETE` | `/{slug}` | Delete organization |
| `GET` | `/{slug}/members` | List organization members |
| `POST` | `/{slug}/members/invite` | Invite a member |
| `POST` | `/invites/{token}/accept` | Accept invitation |
| `PATCH` | `/{slug}/members/{user_id}` | Update member role |
| `DELETE` | `/{slug}/members/{user_id}` | Remove member |

## Playground

Mounted under `/api/v1/playground`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/run` | Execute/simulate a request through a playground endpoint |
| `GET` | `/endpoints` | List available playground endpoints |

The playground is useful for creating request logs, usage records, and dashboard data during development.
