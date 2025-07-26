import sqlite3
import os

DB_PATH = "/opt/wiretide/wiretide.db"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Devices table
cursor.execute("""
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    device_type TEXT DEFAULT 'unknown',
    approved INTEGER DEFAULT 0,
    last_checkin TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# Tokens table
cursor.execute("""
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    description TEXT
);
""")

conn.commit()
conn.close()
print(f"Database initialized at {DB_PATH}")
