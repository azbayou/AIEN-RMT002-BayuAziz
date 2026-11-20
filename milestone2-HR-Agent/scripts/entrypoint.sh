#!/usr/bin/env bash
set -e

# If arguments are provided and the first argument is not uvicorn, run the command directly
if [ "$#" -gt 0 ] && [ "$1" != "uvicorn" ]; then
    exec "$@"
fi

echo "=========================================================="
echo " Starting HR Agent Assistant (Unified API + Web SPA)     "
echo "=========================================================="

# 1. Run database setup / migration if DATABASE_URL is set, not skipped, and DB is unseeded (or FORCE_SETUP=true)
if [ -n "$DATABASE_URL" ] && [ "${SKIP_SETUP:-false}" != "true" ]; then
    if [ "${FORCE_SETUP:-false}" = "true" ] || ! python -c "
import sys
from src.config import get_settings
from src.security import connect_db
s = get_settings()
with connect_db(s.database_url) as conn:
    emp = conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
    chunks = conn.execute('SELECT COUNT(*) FROM policy_chunks').fetchone()[0]
sys.exit(0 if (emp > 0 and chunks > 0) else 1)
" >/dev/null 2>&1; then
        echo "Running database schema migrations & setup..."
        python -m src.setup_lab || {
            echo "Warning: Database setup encountered an error, continuing startup..."
        }
    else
        echo "Database already seeded; skipping setup_lab (set FORCE_SETUP=true to re-run)."
    fi
else
    echo "Skipping database setup (DATABASE_URL not set or SKIP_SETUP=true)."
fi

PORT="${PORT:-8000}"
echo "Server binding to 0.0.0.0:${PORT}..."

# Exec uvicorn to run as PID 1 for proper Unix signal handling (SIGTERM/SIGINT)
exec uvicorn src.api:create_app --factory --host 0.0.0.0 --port "${PORT}"
