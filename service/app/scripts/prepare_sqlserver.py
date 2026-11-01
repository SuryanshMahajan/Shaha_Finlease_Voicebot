"""Create the assignment database without touching the PostgreSQL volume."""
import os
import time

import pymssql


password = os.environ["SQLSERVER_SA_PASSWORD"]
for attempt in range(30):
    try:
        connection = pymssql.connect(
            server="sqlserver", user="sa", password=password,
            database="master", login_timeout=5, timeout=5,
        )
        break
    except pymssql.Error:
        if attempt == 29:
            raise
        time.sleep(2)

try:
    connection.autocommit(True)
    cursor = connection.cursor()
    cursor.execute("SELECT DB_ID(N'shaha_finlease')")
    if cursor.fetchone()[0] is None:
        cursor.execute("CREATE DATABASE [shaha_finlease]")
finally:
    connection.close()
