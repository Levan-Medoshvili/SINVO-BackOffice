"""Database selection without vendor-specific business queries."""
from django.core.exceptions import ImproperlyConfigured


def database_config(env, data_dir):
    engine = env.get("DB_ENGINE", "postgres").lower()
    if engine == "sqlite":
        if env.get("SIMPLEPOS_ALLOW_SQLITE") != "1":
            raise ImproperlyConfigured("SQLite is reserved for local development/tests; set SIMPLEPOS_ALLOW_SQLITE=1.")
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(data_dir / "db.sqlite3"), "OPTIONS": {"timeout": 30}}
    drivers = {"postgres": "django.db.backends.postgresql", "mysql": "django.db.backends.mysql", "mssql": "mssql"}
    if engine not in drivers:
        raise ImproperlyConfigured("DB_ENGINE must be postgres, mysql or mssql.")
    for key in ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST"):
        if not env.get(key):
            raise ImproperlyConfigured(f"{key} is required for {engine}.")
    result = {"ENGINE": drivers[engine], "NAME": env["DB_NAME"], "USER": env["DB_USER"],
        "PASSWORD": env["DB_PASSWORD"], "HOST": env["DB_HOST"],
        "PORT": env.get("DB_PORT", {"postgres": "5432", "mysql": "3306", "mssql": "1433"}[engine]),
        "CONN_MAX_AGE": 60, "CONN_HEALTH_CHECKS": True}
    if engine == "postgres":
        result["OPTIONS"] = {"sslmode": env.get("DB_SSLMODE", "require")}
        if env.get("DB_SSL_CA"):
            result["OPTIONS"]["sslrootcert"] = env["DB_SSL_CA"]
    elif engine == "mysql":
        result["OPTIONS"] = {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'", "isolation_level": "read committed"}
        if env.get("DB_SSL_CA"):
            result["OPTIONS"]["ssl"] = {"ca": env["DB_SSL_CA"]}
    else:
        trust = "yes" if env.get("DB_TRUST_SERVER_CERTIFICATE", "0") == "1" else "no"
        result["OPTIONS"] = {"driver": "ODBC Driver 18 for SQL Server", "extra_params": f"Encrypt=yes;TrustServerCertificate={trust}",
            "connection_timeout": 10, "query_timeout": 30}
    return result
