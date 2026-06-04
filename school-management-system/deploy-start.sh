#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-3}"

echo "Starting portable Django deployment..."
echo "Port: ${PORT}"
echo "Workers: ${WEB_CONCURRENCY}"

if [ "${DEBUG:-False}" != "True" ] && [ "${DEBUG:-False}" != "1" ] && [ -z "${DATABASE_URL:-}" ] && [ "${ALLOW_SQLITE_IN_PRODUCTION:-False}" != "True" ]; then
  echo "ERROR: DATABASE_URL is missing while DEBUG=False."
  echo "Create a PostgreSQL database on your host, then set DATABASE_URL to its connection string."
  echo "For a temporary test only, you can set ALLOW_SQLITE_IN_PRODUCTION=True, but hosted SQLite data is not safe for real school use."
  exit 1
fi

if [ "${SKIP_MIGRATIONS:-False}" != "True" ]; then
  echo "Applying database migrations..."
  python manage.py migrate --noinput
else
  echo "Skipping migrations because SKIP_MIGRATIONS=True"
fi

if [ "${SKIP_COLLECTSTATIC:-False}" != "True" ]; then
  echo "Collecting static files..."
  python manage.py collectstatic --noinput
else
  echo "Skipping collectstatic because SKIP_COLLECTSTATIC=True"
fi

if [ "${BOOTSTRAP_SUPERADMIN:-False}" = "True" ]; then
  echo "Bootstrapping super admin if needed..."
  python manage.py bootstrap_superadmin
fi

echo "Launching Gunicorn..."
exec gunicorn bjs_management.wsgi:application --bind "0.0.0.0:${PORT}" --workers "${WEB_CONCURRENCY}"
