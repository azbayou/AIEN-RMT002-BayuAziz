from __future__ import annotations

from pipelines.ingestion.db import dsn_from_environment


def test_local_profile_uses_explicit_local_url(monkeypatch):
    monkeypatch.setenv("LOCAL_DATABASE_URL", "postgresql://local-user:local-pass@localhost/local_db")
    assert dsn_from_environment("local") == "postgresql://local-user:local-pass@localhost/local_db"


def test_neon_profile_keeps_legacy_postgres_environment(monkeypatch):
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "example.neon.tech")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "demo")
    monkeypatch.setenv("POSTGRES_USER", "demo_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "demo_pass")
    monkeypatch.setenv("POSTGRES_SSLMODE", "require")
    dsn = dsn_from_environment("neon")
    assert "host=example.neon.tech" in dsn
    assert "dbname=demo" in dsn
    assert "password=demo_pass" in dsn


def test_databricks_profile_resolves_dsn_and_values(monkeypatch):
    from shared.db import _profile_values

    monkeypatch.setenv("DATABRICKS_HOST", "https://adb-123456789.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi_secret_token")
    monkeypatch.delenv("DATABRICKS_HTTP_PATH", raising=False)
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "abc123warehouse")
    monkeypatch.setenv("DATABRICKS_CATALOG", "retail_analytics")

    dsn = dsn_from_environment("databricks")
    assert dsn == "databricks://adb-123456789.azuredatabricks.net/retail_analytics"

    values = _profile_values("databricks")
    assert values["host"] == "adb-123456789.azuredatabricks.net"
    assert values["token"] == "dapi_secret_token"
    assert values["http_path"] == "/sql/1.0/warehouses/abc123warehouse"
    assert values["catalog"] == "retail_analytics"
