#!/usr/bin/env python3
import psycopg2
import psycopg2.extras
import textwrap

# --- Configure your connection ---
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_DB   = "dispatcharr"
PG_USER = "dispatch"
PG_PASS = "secret"

# --- Connect ---
conn = psycopg2.connect(
    host=PG_HOST, port=PG_PORT, dbname=PG_DB,
    user=PG_USER, password=PG_PASS
)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# --- Fetch user tables ---
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='public'
      AND table_type='BASE TABLE'
      AND table_name NOT LIKE 'pg_%'
      AND table_name NOT LIKE 'sql_%'
    ORDER BY table_name;
""")
tables = [r['table_name'] for r in cur.fetchall()]

print(f"Found {len(tables)} tables in database '{PG_DB}':\n")

# --- Dump up to 10 rows from each ---
for table in tables:
    print("=" * 80)
    print(f"TABLE: {table}")
    print("-" * 80)

    cur.execute(f"SELECT COUNT(*) FROM {table};")
    count = cur.fetchone()['count']
    print(f"(Total rows: {count})")

    try:
        cur.execute(f"SELECT * FROM {table} LIMIT 10;")
        rows = cur.fetchall()
        if not rows:
            print("(no rows)")
        else:
            for i, row in enumerate(rows, 1):
                print(f"[{i}] {row}")
    except Exception as e:
        print(f"Error reading {table}: {e}")
    print()

conn.close()
