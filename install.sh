#!/bin/bash
set -e

WIRETIDE_DIR="/opt/wiretide"
CERT_DIR="/etc/wiretide/certs"
DB_FILE="$WIRETIDE_DIR/wiretide.db"
LOG_FILE="/var/log/wiretide.log"
REPO_URL="https://github.com/<your-repo>/wiretide-controller.git"
PYTHON_BIN="/usr/bin/python3"

echo "[*] Installing Wiretide Controller..."

# Install system dependencies
apt update && apt install -y nginx python3-venv python3-pip sqlite3 openssl git

# Clone or update repository
mkdir -p "$WIRETIDE_DIR" "$CERT_DIR"
if [ ! -d "$WIRETIDE_DIR/.git" ]; then
    git clone "$REPO_URL" "$WIRETIDE_DIR"
else
    cd "$WIRETIDE_DIR"
    git pull
fi

# Ensure Git doesn't complain about ownership (safe.directory)
git config --global --add safe.directory "$WIRETIDE_DIR"

# Make repo owned by www-data so service can write logs/config
chown -R www-data:www-data "$WIRETIDE_DIR"

cd "$WIRETIDE_DIR"

# Create virtual environment if missing
if [ ! -d venv ]; then
    $PYTHON_BIN -m venv venv
fi

# Make sure venv is writable by service user
chown -R www-data:www-data "$WIRETIDE_DIR/venv"

# Install Python dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Initialize database if it doesn't exist
if [ ! -f "$DB_FILE" ]; then
    echo "[*] Creating SQLite database..."
    source venv/bin/activate
    python db_init.py
    deactivate
fi

# Fix DB and folder permissions for SQLite (locks/journals)
DB_DIR=$(dirname "$DB_FILE")
chown -R www-data:www-data "$DB_FILE" "$DB_DIR"
chmod -R 775 "$DB_DIR"
chmod 664 "$DB_FILE"

# Ensure log file exists and is writable
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chown www-data:www-data "$LOG_FILE"
chmod 664 "$LOG_FILE"

# Generate default API token if none exists
API_TOKEN=$(sqlite3 "$DB_FILE" "SELECT token FROM tokens LIMIT 1;" || true)
if [ -z "$API_TOKEN" ]; then
    API_TOKEN=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)
    sqlite3 "$DB_FILE" "INSERT INTO tokens (token, description) VALUES ('$API_TOKEN', 'Default API Token');"
    echo "[*] Generated new API token for /register and /status"
fi

# Generate self-signed TLS cert (10 years)
if [ ! -f "$CERT_DIR/wiretide.crt" ]; then
    echo "[*] Generating self-signed TLS certificate..."
    openssl req -x509 -nodes -newkey rsa:4096 \
      -keyout "$CERT_DIR/wiretide.key" \
      -out "$CERT_DIR/wiretide.crt" \
      -days 3650 \
      -subj "/CN=wiretide"
fi

# Install systemd service
cp wiretide.service /etc/systemd/system/wiretide.service
systemctl daemon-reload
systemctl enable --now wiretide.service

# Configure Nginx reverse proxy
cp nginx.conf /etc/nginx/sites-available/wiretide
ln -sf /etc/nginx/sites-available/wiretide /etc/nginx/sites-enabled/wiretide
systemctl restart nginx

# Show connection info
IP=$(hostname -I | awk '{print $1}')
echo "==========================================="
echo " Wiretide Controller Installed Successfully"
echo "-------------------------------------------"
echo "Access:   https://$IP/"
echo "Username: admin"
echo "Password: wiretide"
echo "API Token (for agents): $API_TOKEN"
echo "==========================================="

