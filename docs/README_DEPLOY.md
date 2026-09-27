Deployment and Portability Guide

This repo is set up to deploy on Render, Railway, DigitalOcean, Fly.io, Heroku-style platforms, Docker, or a normal VPS.

For the full provider-neutral guide, see `DEPLOYMENT.md`.

Quick production checklist:

- Set `SECRET_KEY` in the provider secret manager.
- Set `DEBUG=False`.
- Use PostgreSQL and set `DATABASE_URL`.
- Set `ALLOWED_HOSTS` to the real domain.
- Set `CSRF_TRUSTED_ORIGINS` for HTTPS domains that submit forms/API requests.
- Configure persistent media storage before storing real school documents/photos.
- Run migrations and collect static files before serving traffic.

Universal start command:

```bash
cd school-management-system
sh deploy-start.sh
```

The same startup script is used by Docker, Procfile-based hosts, and Render blueprint deploys.

Local Docker test:

```bash
docker compose up --build
```

Database switching:

- Local SQLite development: `DEBUG=True` and leave `DATABASE_URL` empty.
- Hosted PostgreSQL: set `DATABASE_URL=postgresql://...`, `DEBUG=False`, and usually `DB_SSL_REQUIRE=True`.
- Local Docker PostgreSQL: use the `docker-compose.yml` defaults.

For real school data, use paid/persistent PostgreSQL with backups. Free databases and temporary disks are useful for testing only.
