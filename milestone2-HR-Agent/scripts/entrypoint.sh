#!/usr/bin/env bash
set -e

# If arguments are provided and the first argument is not uvicorn, run the command directly
if [ "$#" -gt 0 ] && [ "$1" != "uvicorn" ]; then
    exec "$@"
fi

echo "=========================================================="
echo " Starting HR Agent Assistant (Unified API + Web SPA)     "
echo "=========================================================="

# 1. Run database setup / migration if DATABASE_URL is set and SKIP_SETUP is not true
if [ -n "$DATABASE_URL" ] && [ "${SKIP_SETUP:-false}" != "true" ]; then
    echo "Running database schema migrations & setup..."
    python -m src.setup_lab || {
        echo "Warning: Database setup encountered an error, continuing startup..."
    }
else
    echo "Skipping database setup (DATABASE_URL not set or SKIP_SETUP=true)."
fi

PORT="${PORT:-8000}"
echo "Server binding to 0.0.0.0:${PORT}..."

# Exec uvicorn to run as PID 1 for proper Unix signal handling (SIGTERM/SIGINT)
exec uvicorn src.api:create_app --factory --host 0.0.0.0 --port "${PORT}"
