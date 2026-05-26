#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

APP_NAME="school-management-system"
EXPORT_DIR="exports"
STAMP=$(date +"%Y%m%d-%H%M%S")
STAGE="${TMPDIR:-/tmp}/${APP_NAME}-move-${STAMP}"

mkdir -p "$EXPORT_DIR"

printf "\nSchool Management System Move Tool\n"
printf "----------------------------------\n"
printf "1. Build code-only ZIP for a new provider\n"
printf "2. Build ZIP with media uploads\n"
printf "3. Build ZIP with media and local SQLite database\n"
printf "4. Build sensitive full ZIP with media, SQLite database, and .env\n"
printf "5. Build TAR.GZ with media uploads\n"
printf "6. Show provider migration checklist\n\n"
printf "Choose an option [1-6]: "
read CHOICE

FORMAT="zip"
INCLUDE_MEDIA="0"
INCLUDE_DB="0"
INCLUDE_ENV="0"

case "$CHOICE" in
  1) ;;
  2) INCLUDE_MEDIA="1" ;;
  3) INCLUDE_MEDIA="1"; INCLUDE_DB="1" ;;
  4)
    INCLUDE_MEDIA="1"; INCLUDE_DB="1"; INCLUDE_ENV="1"
    printf "\nWARNING: This package may contain secrets and real school data.\n"
    printf "Type YES to continue: "
    read CONFIRM
    [ "$CONFIRM" = "YES" ] || exit 1
    ;;
  5) FORMAT="tar"; INCLUDE_MEDIA="1" ;;
  6)
    cat <<'EOF'

Provider migration checklist
----------------------------
1. Create PostgreSQL on the new provider and copy DATABASE_URL.
2. Set SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS if needed.
3. Set email/SMS/mobile money/API credentials in provider environment variables.
4. Upload or connect persistent media storage. Local Render disk is not permanent on free web services.
5. Deploy, then run migrations and collectstatic.
6. Confirm login, payments, report cards, payroll dashboard, and parent portal.

EOF
    exit 0
    ;;
  *) printf "Invalid option.\n"; exit 1 ;;
esac

rm -rf "$STAGE"
mkdir -p "$STAGE"

if command -v rsync >/dev/null 2>&1; then
  rsync -a ./ "$STAGE"/ \
    --exclude ".git/" \
    --exclude ".github/" \
    --exclude ".venv/" \
    --exclude "venv/" \
    --exclude "env/" \
    --exclude "ENV/" \
    --exclude "node_modules/" \
    --exclude "staticfiles/" \
    --exclude "__pycache__/" \
    --exclude "$EXPORT_DIR/" \
    --exclude "*.pyc" \
    --exclude "*.pyo" \
    --exclude "*.pyd" \
    --exclude "*.log" \
    --exclude "db.sqlite3-journal" \
    --exclude "runserver_*.err" \
    --exclude "runserver_*.out" \
    --exclude "tmpstart*.err" \
    --exclude "tmpstart*.out" \
    --exclude "start_*.err" \
    --exclude "start_*.out" \
    --exclude "admin_probe.err" \
    --exclude "admin_probe.out" \
    --exclude "debug_index_script.js" \
    --exclude "debug-test.html" \
    --exclude "test-sidebar-render.html" \
    --exclude "quick_test.py" \
    --exclude "tmp_buildsidebar_test.js" \
    --exclude "GRADING_SCALE_UI_GUIDE.md" \
    --exclude "SYSTEM_ENHANCEMENTS.md" \
    --exclude "school-management-system/school/settings.py"
else
  tar \
    --exclude="./.git" \
    --exclude="./.github" \
    --exclude="./.venv" \
    --exclude="./venv" \
    --exclude="./env" \
    --exclude="./ENV" \
    --exclude="./node_modules" \
    --exclude="./staticfiles" \
    --exclude="./__pycache__" \
    --exclude="./$EXPORT_DIR" \
    --exclude="*.pyc" \
    --exclude="*.pyo" \
    --exclude="*.pyd" \
    --exclude="*.log" \
    --exclude="db.sqlite3-journal" \
    --exclude="runserver_*.err" \
    --exclude="runserver_*.out" \
    --exclude="tmpstart*.err" \
    --exclude="tmpstart*.out" \
    --exclude="start_*.err" \
    --exclude="start_*.out" \
    --exclude="admin_probe.err" \
    --exclude="admin_probe.out" \
    --exclude="debug_index_script.js" \
    --exclude="debug-test.html" \
    --exclude="test-sidebar-render.html" \
    --exclude="quick_test.py" \
    --exclude="tmp_buildsidebar_test.js" \
    --exclude="GRADING_SCALE_UI_GUIDE.md" \
    --exclude="SYSTEM_ENHANCEMENTS.md" \
    --exclude="school-management-system/school/settings.py" \
    -cf - . | tar -xf - -C "$STAGE"
fi

[ "$INCLUDE_MEDIA" = "1" ] || rm -rf "$STAGE/school-management-system/media"
[ "$INCLUDE_DB" = "1" ] || rm -f "$STAGE/school-management-system/db.sqlite3"
if [ "$INCLUDE_ENV" != "1" ]; then
  rm -f "$STAGE/.env" "$STAGE/school-management-system/.env"
fi

cat > "$STAGE/MOVE_MANIFEST.txt" <<EOF
Built: $(date)
Source: $ROOT_DIR
Include media: $INCLUDE_MEDIA
Include sqlite database: $INCLUDE_DB
Include env secrets: $INCLUDE_ENV

After upload to a provider:
1. Set SECRET_KEY, DEBUG=False, ALLOWED_HOSTS, DATABASE_URL.
2. Run python manage.py migrate --noinput.
3. Run python manage.py collectstatic --noinput.
4. Run python manage.py bootstrap_superadmin only when needed.
5. Start gunicorn bjs_management.wsgi:application.
EOF

OUT="$EXPORT_DIR/${APP_NAME}-${STAMP}"
if [ "$FORMAT" = "tar" ]; then
  tar -czf "$OUT.tar.gz" -C "$STAGE" .
  ARCHIVE="$OUT.tar.gz"
else
  if command -v zip >/dev/null 2>&1; then
    (cd "$STAGE" && zip -qr "$ROOT_DIR/$OUT.zip" .)
  else
    python -m zipfile -c "$OUT.zip" "$STAGE"
  fi
  ARCHIVE="$OUT.zip"
fi

rm -rf "$STAGE"

printf "\nPackage created:\n%s\n\n" "$ARCHIVE"
printf "Keep sensitive packages private if you included .env or db.sqlite3.\n"
