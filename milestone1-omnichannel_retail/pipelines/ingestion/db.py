"""Backward-compatibility alias pointing to shared.db."""
from shared.db import apply_sql_file, connect, dsn_from_environment

__all__ = ["apply_sql_file", "connect", "dsn_from_environment"]
