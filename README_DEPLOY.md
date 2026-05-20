Deployment and Portability Guide

Quick checklist before production:

- Set `SECRET_KEY` in environment (do not commit).
- Set `DEBUG=False` in environment.
- Use a production Postgres database and set `DATABASE_URL`.
- Configure `BOOTSTRAP_SUPERADMIN_PASSWORD` via secrets if you enable bootstrapping.
- If you accept file uploads in production, enable `USE_S3=True` and set AWS credentials, or configure persistent storage.

Deploy options:

1) Render
- Create a new Web Service using the GitHub repo.
- Set `root` to `school-management-system`.
- Add required secrets: `SECRET_KEY`, `DATABASE_URL` (if using managed DB), `BOOTSTRAP_SUPERADMIN_PASSWORD`, `TWILIO_*`.
- Trigger deploy; Render will run migrations and start `gunicorn` as configured in `render.yaml`.

2) Docker (self-host or other providers)
- Build and run locally with Docker Compose (Postgres included):

```bash
docker-compose up --build
```

- For production, build the image and push to your container registry, then run on your host with env vars set.

Local startup helper
- Windows: run `school-management-system\start.bat`.
- Linux/macOS: run `school-management-system/start.sh`.
- Both wrappers call `setup_env.py`, which creates the venv, installs dependencies, migrates the database, collects static files, and starts the server.

3) Heroku/Railway
- Use `Procfile` and set environment variables in the platform dashboard.
- Ensure you provide `DATABASE_URL` for Postgres and `SECRET_KEY`.

Portability notes
- Use `DATABASE_URL` for DB connection; this makes swapping DB providers trivial.
- Store secrets in the provider's secret manager rather than in repo.
- Use Docker for the most portable deploy; the included `Dockerfile` and `docker-compose.yml` support common providers.
- Migrate static & media:
  - `collectstatic` is run during build/start for Docker/Render.
  - For persistent media across hosts use S3 or another object store.

Reducing latency
- Use a CDN for static assets if you expect global traffic.
- Enable caching headers (already configured via WhiteNoise when available).
- Use a managed Postgres close to your users.
- Increase Gunicorn worker count for CPU-bound workloads and tune worker class for async if needed.

Rollback & updates
- When you push to GitHub and auto-deploy is enabled the host will redeploy on new commits.
- For manual hosts, push the image or run database migrations carefully and keep backups.

If you want, I can:
- Push these changes to GitHub now.
- Walk through creating a Render service and setting secrets step-by-step.
- Add GitHub Actions to build/publish Docker images automatically.
