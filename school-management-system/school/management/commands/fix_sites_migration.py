from django.core.management.base import BaseCommand
from django.conf import settings

import datetime
import sqlite3


class Command(BaseCommand):
    help = "Fix inconsistent migration history for django.contrib.sites (SQLite dev helper)."

    def handle(self, *args, **options):
        db = settings.DATABASES.get("default", {})
        if db.get("ENGINE") != "django.db.backends.sqlite3":
            self.stdout.write("fix_sites_migration: only supports SQLite.")
            return

        path = str(db.get("NAME"))
        if not path:
            self.stderr.write("fix_sites_migration: missing sqlite path.")
            return

        now = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")

        con = sqlite3.connect(path)
        try:
            cur = con.cursor()

            # Ensure sites table exists for allauth FK use.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS django_site (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain varchar(100) NOT NULL UNIQUE,
                    name varchar(50) NOT NULL
                )
                """
            )

            # Ensure site id=1 exists (Django assumes this often).
            cur.execute("SELECT id FROM django_site WHERE id = 1")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO django_site (id, domain, name) VALUES (1, ?, ?)",
                    ("localhost", "Bitende Junior School"),
                )

            # Mark migrations as applied to satisfy dependency order check.
            # socialaccount.0001 depends on sites.0001; in some dev DBs it ends up inverted.
            cur.execute(
                "CREATE TABLE IF NOT EXISTS django_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, app varchar(255) NOT NULL, name varchar(255) NOT NULL, applied datetime NOT NULL)"
            )

            for name in ["0001_initial", "0002_alter_domain_unique"]:
                cur.execute("SELECT 1 FROM django_migrations WHERE app = 'sites' AND name = ?", (name,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO django_migrations (app, name, applied) VALUES ('sites', ?, ?)",
                        (name, now),
                    )

            con.commit()
            self.stdout.write("fix_sites_migration: ensured django_site and marked sites migrations applied.")
        finally:
            con.close()

