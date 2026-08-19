import os
import psycopg2

SEED_SQL = """
INSERT INTO municipalities (id, name, created_at)
VALUES ('municipality-lahore', 'City of Lahore', NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO bridges (id, municipality_id, name, location, created_at)
VALUES
  ('bridge-ravi-01', 'municipality-lahore',
   'Ravi River Bridge', 'Lahore, Punjab', NOW()),
  ('bridge-data-01', 'municipality-lahore',
   'Data Darbar Underpass', 'Lahore, Punjab', NOW()),
  ('bridge-mall-01', 'municipality-lahore',
   'Mall Road Overpass', 'Lahore, Punjab', NOW()),
  ('bridge-thokar-01', 'municipality-lahore',
   'Thokar Niaz Baig Bridge', 'Lahore, Punjab', NOW())
ON CONFLICT (id) DO NOTHING;

INSERT INTO sensors (id, bridge_id, sensor_type, config, created_at)
VALUES
  ('acc-ravi-01', 'bridge-ravi-01', 'accelerometer',
   '{"expected_interval_s": 10}', NOW()),
  ('acc-data-01', 'bridge-data-01', 'accelerometer',
   '{"expected_interval_s": 10}', NOW()),
  ('acc-mall-01', 'bridge-mall-01', 'accelerometer',
   '{"expected_interval_s": 10}', NOW()),
  ('acc-thokar-01', 'bridge-thokar-01', 'accelerometer',
   '{"expected_interval_s": 10}', NOW())
ON CONFLICT (id) DO NOTHING;
"""

def seed():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL not set")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(SEED_SQL)
    cur.close()
    conn.close()
    print("Seed data inserted.")

if __name__ == "__main__":
    seed()