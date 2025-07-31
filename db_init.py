import sqlite3
import os
from passlib.hash import bcrypt

DB_PATH = "/opt/wiretide/wiretide.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# --- Devices table ---
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
    status_json TEXT,
    agent_update_allowed BOOLEAN DEFAULT 0,
    agent_version TEXT DEFAULT '0.1.0'
);
""")


# --- Device status table ---
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

# --- Device configs table ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS device_configs (
    mac TEXT PRIMARY KEY,
    config TEXT,
    created_at TIMESTAMP
);
""")

# --- Tokens table ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL UNIQUE,
    description TEXT
);
""")

# --- Config table ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

# --- Users table ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'admin',
    role_id INTEGER
);
""")

# --- Roles & Permissions tables (RBAC) ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER,
    permission TEXT NOT NULL,
    FOREIGN KEY(role_id) REFERENCES roles(id),
    UNIQUE(role_id, permission)
);
""")


# --- Seed roles if missing ---
cursor.execute("SELECT COUNT(*) FROM roles")
role_count = cursor.fetchone()[0]
if role_count == 0:
    cursor.execute("INSERT INTO roles (name) VALUES ('admin')")
    cursor.execute("INSERT INTO roles (name) VALUES ('user')")

# --- Seed default permissions ---
# Admin: full access
cursor.execute("""
INSERT OR IGNORE INTO role_permissions (role_id, permission)
SELECT id, '*' FROM roles WHERE name='admin'
""")

# User: read-only (view only)
for perm in ['devices:view', 'status:view']:
    cursor.execute("""
    INSERT OR IGNORE INTO role_permissions (role_id, permission)
    SELECT id, ? FROM roles WHERE name='user'
    """, (perm,))

# --- Link users to roles ---
# If role_id missing, assign based on role name
cursor.execute("SELECT COUNT(*) FROM users")
if cursor.fetchone()[0] > 0:
    cursor.execute("""
    UPDATE users
    SET role_id = (SELECT id FROM roles WHERE name = users.role)
    WHERE role_id IS NULL
    """)
    
# Ensure admin has roles:manage explicitly (even though '*' exists)
cursor.execute("""
INSERT OR IGNORE INTO role_permissions (role_id, permission)
SELECT id, 'roles:manage' FROM roles WHERE name='admin'
""")


# --- Seed default admin user if none ---
cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
if cursor.fetchone()[0] == 0:
    password_hash = bcrypt.hash("wiretide")
    # Get admin role_id
    cursor.execute("SELECT id FROM roles WHERE name='admin'")
    admin_role_id = cursor.fetchone()[0]
    cursor.execute(
        "INSERT INTO users (username, password_hash, role, role_id) VALUES (?, ?, ?, ?)",
        ('admin', password_hash, 'admin', admin_role_id)
    )
    print("Default admin user created: username=admin, password=wiretide")

# --- Seed default agent update config ---
cursor.execute("""
INSERT OR IGNORE INTO config (key, value) VALUES
('agent_updates_enabled', 'false')
""")
cursor.execute("""
INSERT OR IGNORE INTO config (key, value) VALUES
('agent_update_url', '/static/agent/agent-update-v0.5.5.sh')
""")
cursor.execute("""
INSERT OR IGNORE INTO config (key, value) VALUES
('min_supported_agent_version', '0.1.0')
""")

conn.commit()
conn.close()
print(f"Database initialized at {DB_PATH}")



