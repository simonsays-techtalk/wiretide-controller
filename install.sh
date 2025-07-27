#!/bin/bash
set -e

WIRETIDE_DIR="/opt/wiretide"
CERT_DIR="/etc/wiretide/certs"
STATIC_DIR="$WIRETIDE_DIR/wiretide/static"
DB_FILE="$WIRETIDE_DIR/wiretide.db"
LOG_FILE="/var/log/wiretide.log"
REPO_URL="https://github.com/<your-repo>/wiretide-controller.git"
PYTHON_BIN="/usr/bin/python3"

echo "[*] Installing Wiretide Controller..."

# Install system dependencies
apt update && apt install -y nginx python3-venv python3-pip sqlite3 openssl git curl

# Ensure Git won't block due to ownership
git config --global --add safe.directory "$WIRETIDE_DIR" || true

# Clone or update repository
mkdir -p "$WIRETIDE_DIR" "$CERT_DIR"
if [ ! -d "$WIRETIDE_DIR/.git" ]; then
    git clone "$REPO_URL" "$WIRETIDE_DIR"
else
    cd "$WIRETIDE_DIR"
    git pull
fi

# Ensure repo is owned by www-data for runtime access
chown -R www-data:www-data "$WIRETIDE_DIR"

cd "$WIRETIDE_DIR"

# Create virtual environment if missing
if [ ! -d venv ]; then
    $PYTHON_BIN -m venv venv
fi

# Ensure venv is writable
chown -R www-data:www-data "$WIRETIDE_DIR/venv"

# Install Python dependencies
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Ensure static folder exists (for logo and agent files)
mkdir -p "$STATIC_DIR"
chown -R www-data:www-data "$STATIC_DIR"

# Add a default logo if missing (optional placeholder)
if [ ! -f "$STATIC_DIR/wiretide_logo.png" ]; then
    echo "[*] Adding default placeholder logo..."
    # Small base64 placeholder image (1x1 transparent PNG)
    base64 -d > "$STATIC_DIR/wiretide_logo.png" <<'EOF'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEklEQVR42mP8z8BQDwADgwHBEdkDTwAAAABJRU5ErkJggg==
EOF
    chown www-data:www-data "$STATIC_DIR/wiretide_logo.png"
fi

# Initialize database if missing
if [ ! -f "$DB_FILE" ]; then
    echo "[*] Creating SQLite database..."
    source venv/bin/activate
    python db_init.py
    deactivate
fi

# Fix DB permissions (SQLite needs folder and file write access)
DB_DIR=$(dirname "$DB_FILE")
chown -R www-data:www-data "$DB_FILE" "$DB_DIR"
chmod -R 775 "$DB_DIR"
chmod 664 "$DB_FILE"

# Ensure log file exists and is writable
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chown www-data:www-data "$LOG_FILE"
chmod 664 "$LOG_FILE"

# Generate API token if none exists
API_TOKEN=$(sqlite3 "$DB_FILE" "SELECT token FROM tokens LIMIT 1;" || true)
if [ -z "$API_TOKEN" ]; then
    API_TOKEN=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)
    sqlite3 "$DB_FILE" "INSERT INTO tokens (token, description) VALUES ('$API_TOKEN', 'Default API Token');"
    echo "[*] Generated new API token for /register and /status"
fi

# Generate TLS certificate (10 years)
if [ ! -f "$CERT_DIR/wiretide.crt" ]; then
    echo "[*] Generating self-signed TLS certificate..."
    openssl req -x509 -nodes -newkey rsa:4096 \
      -keyout "$CERT_DIR/wiretide.key" \
      -out "$CERT_DIR/wiretide.crt" \
      -days 3650 \
      -subj "/CN=wiretide"
fi

# Install and start systemd service
cp wiretide.service /etc/systemd/system/wiretide.service
systemctl daemon-reload
systemctl enable --now wiretide.service

# Configure Nginx proxy
cp nginx.conf /etc/nginx/sites-available/wiretide
ln -sf /etc/nginx/sites-available/wiretide /etc/nginx/sites-enabled/wiretide
systemctl restart nginx

# Health check
echo "[*] Checking if Wiretide service is running..."
sleep 3
if ! curl -sk https://127.0.0.1/ > /dev/null; then
    echo "[!] Wiretide service might not be running correctly. Showing logs:"
    journalctl -u wiretide --no-pager -n 50
else
    echo "[*] Wiretide is up and reachable locally."
fi

# Connection details
IP=$(hostname -I | awk '{print $1}')
echo "==========================================="
echo " Wiretide Controller Installed Successfully"
echo "-------------------------------------------"
echo "Access:   https://$IP/"
echo "Username: admin"
echo "Password: wiretide"
echo "API Token (for agents): $API_TOKEN"
echo "==========================================="

