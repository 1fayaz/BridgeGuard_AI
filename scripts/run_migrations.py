import os
import psycopg2
import glob

def run_migrations():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL not set")

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()

    migrations = sorted(glob.glob("db/migrations/*.sql"))
    print(f"Found {len(migrations)} migrations")

    for path in migrations:
        name = os.path.basename(path)
        print(f"Running {name}...")
        with open(path) as f:
            sql = f.read()
        try:
            cur.execute(sql)
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            raise

    cur.close()
    conn.close()
    print("All migrations complete.")

if __name__ == "__main__":
    run_migrations()