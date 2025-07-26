import sqlite3
import os
import hashlib

DB_PATH = "/opt/wiretide/wiretide.db"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def hash_password(password: str) -> str:
    # Simple SHA256 for now (upgrade to bcrypt later)
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

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

# Users table (for admin login)
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
""")

# Seed default admin if not exists
cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
if cursor.fetchone()[0] == 0:
    cursor.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ('admin', hash_password('wiretide'))
    )
    print("Default admin user created: username=admin, password=wiretide")

conn.commit()
conn.close()
print(f"Database initialized at {DB_PATH}")
