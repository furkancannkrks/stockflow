# StockFlow

StockFlow is a Django-based inventory and order reservation management system.

## Database and Environment Setup

StockFlow is configured to use PostgreSQL for development and production. It does
not use SQLite as a fallback database.

Create a local `.env` file from the example values:

```bash
cp .env.example .env
```

Update the values in `.env` for your local PostgreSQL user, password, database,
host, and port. Do not commit real secrets or local credentials.

The Django settings read these environment variables:

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
```

Celery uses Redis as its broker and result backend. When running directly on the
host, the example URLs connect to Redis on `localhost`.

## Docker Compose

The Compose stack contains:

- `web`: Django development server
- `db`: PostgreSQL with a persistent named volume
- `redis`: Celery broker and result backend
- `celery_worker`: Celery worker
- `celery_beat`: the single reservation-expiration scheduler

`web`, `celery_worker`, and `celery_beat` use the same application image.
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
