#!/bin/bash
set -e
echo "Running migrations..."
PYTHONPATH=/app/src python db/migrate.py
echo "Seeding data..."
PYTHONPATH=/app/src python db/seed.py
echo "Starting API..."
exec env PYTHONPATH=/app/src uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8080}