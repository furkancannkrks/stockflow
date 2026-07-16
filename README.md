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

`CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` are present now as configuration
placeholders. Later Celery prompts will use Redis at those URLs for background
jobs and result storage.

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
