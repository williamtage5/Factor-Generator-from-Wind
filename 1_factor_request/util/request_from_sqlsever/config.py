import os


class SQLConfig:
    """Local SQL Server config."""

    SQL_SERVER = os.getenv("SQL_SERVER", ".")
    SQL_DATABASE = os.getenv("SQL_DATABASE", "winddb20260405")
    SQL_USERNAME = os.getenv("SQL_USERNAME", "")
    SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")

