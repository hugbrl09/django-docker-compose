#!/bin/sh
set -e

DB_HOST="${POSTGRES_HOST:-db}"
DB_PORT="${POSTGRES_PORT:-5432}"

echo "[entrypoint] aguardando PostgreSQL em ${DB_HOST}:${DB_PORT} ..."
until python -c "
import os, socket, sys
s = socket.socket()
s.settimeout(1)
try:
    s.connect((os.environ.get('POSTGRES_HOST', 'db'),
               int(os.environ.get('POSTGRES_PORT', '5432'))))
except OSError:
    sys.exit(1)
" 2>/dev/null; do
  sleep 1
done
echo "[entrypoint] PostgreSQL respondeu."

echo "[entrypoint] aplicando migrations..."
python manage.py migrate --noinput

echo "[entrypoint] coletando arquivos estaticos..."
python manage.py collectstatic --noinput --clear

echo "[entrypoint] iniciando: $@"
exec "$@"
