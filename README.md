# StockFlow

StockFlow is a Django-based inventory and order reservation management system.

## Local Development

StockFlow is configured to use PostgreSQL for development and production. It does
not use SQLite as a fallback database.

Create a local `.env` file from the example values:

```bash
cp .env.example .env
```

Update the values in `.env` for your local PostgreSQL user, password, database,
host, and port. Do not commit real secrets or local credentials.

The default `config.settings` module is intended for local development. It reads
`.env`, defaults `DJANGO_DEBUG` to `True`, and permits the local hosts
`localhost` and `127.0.0.1`. The fallback secret is deliberately development
only.

The development settings read these environment variables:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

For a local PostgreSQL setup, create the user and database with commands similar
to:

```sql
CREATE USER stockflow WITH PASSWORD 'replace-this-with-a-local-password';
CREATE DATABASE stockflow OWNER stockflow;
```

Then install dependencies and run migrations:

```bash
py -3 -m pip install -r requirements.txt
py -3 manage.py migrate
py -3 manage.py runserver
```

Celery uses Redis as its broker and result backend. When running directly on the
host, the example URLs connect to Redis on `localhost`.

## Docker Development

The Compose stack contains:

- `web`: Django development server
- `db`: PostgreSQL with a persistent named volume
- `redis`: Celery broker and result backend
- `celery_worker`: Celery worker
- `celery_beat`: the single reservation-expiration scheduler

`web`, `celery_worker`, and `celery_beat` use the same application image. The
base `docker-compose.yml` intentionally keeps Django's `runserver` for the
existing local Docker development workflow and explicitly selects
`config.settings`.
Compose overrides the database and Redis hostnames with the service names `db`
and `redis`. The committed fallback credentials are development placeholders;
put local values in `.env` and never commit real secrets.

Validate the resolved configuration:

```bash
docker compose config
```

For the simplest startup, build and start the complete stack, then run
migrations explicitly:

```bash
docker compose up --build -d
docker compose exec web python manage.py migrate
```

On a completely empty database, this sequence avoids Beat dispatching a task
before migrations have been applied:

```bash
docker compose build
docker compose up -d db redis
docker compose run --rm web python manage.py migrate
docker compose up -d
```

Migrations and demo data are never run automatically. Run them deliberately:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_data
```

Run Django checks and the test suite inside the shared application image:

```bash
docker compose exec web python manage.py check
docker compose exec web pytest
```

The `/health/` endpoint performs a lightweight `SELECT 1`. The web container is
healthy only when Django is responding and PostgreSQL is reachable.

Confirm PostgreSQL and Redis connectivity:

```bash
docker compose exec db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec redis redis-cli ping
```

Inspect Celery worker availability and registered tasks:

```bash
docker compose exec celery_worker celery -A config inspect ping
docker compose exec celery_worker celery -A config inspect registered
```

The registered task list should include
`apps.orders.tasks.expire_reserved_orders`. Inspect worker and scheduler logs
with:

```bash
docker compose logs celery_worker
docker compose logs celery_beat
```

Compose defines one `celery_beat` service with the fixed container name
`stockflow_celery_beat`, preventing that scheduler from being scaled into
multiple simultaneous instances. The application containers receive `SIGTERM`
and have a 30-second stop grace period:

```bash
docker compose stop -t 30
docker compose down
```

## Production-Like Docker

Production settings use `config.settings_production`. This module:

- requires a strong `DJANGO_SECRET_KEY` of at least 50 characters
- requires `DJANGO_ALLOWED_HOSTS`
- requires `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and `DB_HOST`
- rejects `DJANGO_DEBUG=True`
- defaults HTTPS redirect, secure session cookies, secure CSRF cookies, and
  one year of HSTS to enabled
- uses persistent database connections with health checks
- serves collected static assets through WhiteNoise

HSTS preload remains disabled by default because browser preload registration
should happen only after the real domain and all subdomains are confirmed to
support HTTPS permanently.

The tracked `.env.example` contains placeholders only. Use deployment-specific
environment injection or an untracked `.env` file. A secret can be generated
locally without storing it in the repository:

```powershell
$env:DJANGO_SECRET_KEY = py -3 -c "import secrets; print(secrets.token_urlsafe(64))"
$env:DJANGO_ALLOWED_HOSTS = "stockflow.example.com,localhost"
$env:DJANGO_CSRF_TRUSTED_ORIGINS = "https://stockflow.example.com"
$env:DB_NAME = "stockflow"
$env:DB_USER = "stockflow"
$env:DB_PASSWORD = "set-a-deployment-specific-password"
```

Validate and start the production-like override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

The production web process runs Gunicorn rather than `runserver`. Static files
are collected when that web container starts. Database migrations and demo data
remain explicit:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py migrate
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py seed_data
```

Verify the deployment settings:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py check --deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Production defaults assume HTTPS is terminated by a trusted reverse proxy.
Set `DJANGO_TRUST_PROXY_HEADERS=True` only when that proxy controls
`X-Forwarded-Proto`. The Compose health check sends that header so readiness can
be checked behind the same proxy model. Disable HTTPS redirect or secure
cookies only for a deliberate local production-mode diagnostic, never for an
internet-facing deployment.

Production Compose clears the optional demo-user password variables. Running
`seed_data` in this mode therefore creates demo users with unusable passwords
unless the command's behavior is deliberately changed outside this Compose
configuration.

## Demo Data

Create or refresh the deterministic demonstration dataset with:

```bash
py -3 manage.py seed_data
```

The command is safe to run repeatedly. It creates deterministic products,
warehouses, inventory, order scenarios, stock movements, and audit records.

Demo usernames:

- `demo_manager` with the `manager` role
- `demo_warehouse_staff` with the `warehouse_staff` role

No password is stored in the repository. New demo users receive unusable
passwords unless these optional environment variables are set before running
the command:

- `STOCKFLOW_DEMO_MANAGER_PASSWORD`
- `STOCKFLOW_DEMO_STAFF_PASSWORD`

The command never prints the configured password values.
