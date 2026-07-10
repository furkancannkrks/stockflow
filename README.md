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
