import sqlite3
import os
from passlib.hash import bcrypt

DB_PATH = "/opt/wiretide/wiretide.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Devices table
cursor.execute("""
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname TEXT NOT NULL,
    mac TEXT NOT NULL UNIQUE,
    ip TEXT,
    ssh_fingerprint TEXT,
    ssh_enabled INTEGER DEFAULT 1,
    status TEXT DEFAULT 'waiting',
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    device_type TEXT DEFAULT 'unknown',
    approved INTEGER DEFAULT 0,
    status_json TEXT
);
""")

# Device status table (summary data)
cursor.execute("""
CREATE TABLE IF NOT EXISTS device_status (
    mac TEXT PRIMARY KEY,
    model TEXT,
    wan_ip TEXT,
    dns_servers TEXT,
    ntp_synced INTEGER,
    firewall_state TEXT,
    updated_at TIMESTAMP
);
""")

# Device configs (queued config)
cursor.execute("""
CREATE TABLE IF NOT EXISTS device_configs (
    mac TEXT PRIMARY KEY,
    config TEXT,
    created_at TIMESTAMP
);
""")

# Tokens table (for agents)
cursor.execute("""
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    description TEXT
);
""")

# Config table (legacy shared token support)
cursor.execute("""
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

# Users table
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'admin'
);
""")

# Seed default admin
cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
if cursor.fetchone()[0] == 0:
    password_hash = bcrypt.hash("wiretide")
    cursor.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        ('admin', password_hash, 'admin')
    )
    print("Default admin user created: username=admin, password=wiretide")

conn.commit()
conn.close()
print(f"Database initialized at {DB_PATH}")

