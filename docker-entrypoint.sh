#!/usr/bin/env sh
# Bring the schema up to date before serving, so a fresh container against an
# empty database is immediately usable and an upgraded image migrates itself.
set -e

echo "quartermaster: applying migrations..."
alembic upgrade head

if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "quartermaster: seeding sample data..."
  python -m scripts.seed
fi

exec "$@"
