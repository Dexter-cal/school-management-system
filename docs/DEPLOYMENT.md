# Portable Deployment Guide

This project can run on Render, Railway, DigitalOcean, Fly.io, Heroku-style platforms, Docker, or a normal VPS.

The main rule is simple: set environment variables, install `school-management-system/requirements.txt`, then run `school-management-system/deploy-start.sh`.

## Required Environment Variables

```env
SECRET_KEY=change-me-to-a-long-random-secret
DEBUG=False
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
DATABASE_URL=postgresql://user:password@host:5432/database
DB_SSL_REQUIRE=True
ALLOW_SQLITE_IN_PRODUCTION=False
```

Use `DB_SSL_REQUIRE=True` for most hosted Postgres providers. Use `False` for local Docker/Postgres.

## Universal Start Command

From inside `school-management-system`:

```bash
./deploy-start.sh
```

If the platform needs a one-line command:

```bash
python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn bjs_management.wsgi:application --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-3}
```

## Optional Environment Variables

```env
PORT=8000
WEB_CONCURRENCY=3
SKIP_MIGRATIONS=False
SKIP_COLLECTSTATIC=False
BOOTSTRAP_SUPERADMIN=False
BOOTSTRAP_SUPERADMIN_USERNAME=admin
BOOTSTRAP_SUPERADMIN_PASSWORD=
BOOTSTRAP_SUPERADMIN_EMAIL=admin@example.com
CSRF_TRUSTED_ORIGINS=https://your-domain.com
```

## Switching Databases

Local SQLite for development:

```env
DEBUG=True
DATABASE_URL=
```

Hosted Postgres:

```env
DEBUG=False
DATABASE_URL=postgresql://user:password@host:5432/database
DB_SSL_REQUIRE=True
```

Local Docker Postgres:

```env
DEBUG=True
DATABASE_URL=postgresql://bjsuser:bjspassword@db:5432/bjsdb
DB_SSL_REQUIRE=False
```

## Docker

```bash
docker compose up --build
```

Docker Compose runs Postgres and points Django to it automatically.

## Provider Notes

Render, Railway, DigitalOcean, Fly.io, and similar platforms all work as long as they provide:

- Python 3.12+
- PostgreSQL database URL
- A persistent domain added to `ALLOWED_HOSTS`
- `SECRET_KEY`

For real school data, use a paid/persistent Postgres database and configure backups.

## Render Manual Deploy

If you create a normal Render Web Service manually, Render does not automatically create the database from `render.yaml`.

Do this in the Render dashboard:

1. Create a PostgreSQL database.
2. Copy the database internal/external connection string.
3. Open the Web Service environment variables.
4. Add `DATABASE_URL` with the copied PostgreSQL connection string.
5. Add `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS=.onrender.com,your-domain.com`, `DB_SSL_REQUIRE=True`, and `ALLOW_SQLITE_IN_PRODUCTION=False`.
6. Redeploy.

If you use Render Blueprint instead, the `render.yaml` can create and link the database automatically.
