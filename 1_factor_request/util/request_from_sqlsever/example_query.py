try:
    from .sql_server_client import run_query
except ImportError:  # direct script execution fallback
    from sql_server_client import run_query


def main() -> None:
    sql = """
    SELECT TOP 5
        TABLE_SCHEMA,
        TABLE_NAME
    FROM INFORMATION_SCHEMA.TABLES
    ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    df = run_query(sql)
    print(df)


if __name__ == "__main__":
    main()
