#!/bin/bash
set -e

WIRETIDE_DIR="/opt/wiretide"
CERT_DIR="/etc/wiretide/certs"
DB_FILE="$WIRETIDE_DIR/wiretide.db"
REPO_URL="https://github.com/<your-repo>/wiretide-controller.git"
PYTHON_BIN="/usr/bin/python3"

echo "[*] Installing Wiretide Controller..."

# Update system
apt update && apt install -y nginx python3-venv python3-pip sqlite3 openssl git

# Create directories
mkdir -p "$WIRETIDE_DIR" "$CERT_DIR"

# Clone or update repo
if [ ! -d "$WIRETIDE_DIR/.git" ]; then
    git clone "$REPO_URL" "$WIRETIDE_DIR"
else
    cd "$WIRETIDE_DIR"
    git pull
fi

# Setup virtual environment
cd "$WIRETIDE_DIR"
if [ ! -d venv ]; then
    $PYTHON_BIN -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Initialize database
if [ ! -f "$DB_FILE" ]; then
    echo "[*] Creating SQLite database..."
    $PYTHON_BIN db_init.py
fi

# Generate self-signed TLS certificate (10 years)
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

# Configure Nginx
cp nginx.conf /etc/nginx/sites-available/wiretide
ln -sf /etc/nginx/sites-available/wiretide /etc/nginx/sites-enabled/wiretide
systemctl restart nginx

echo "[*] Installation complete!"
echo "Access Wiretide at: https://$(hostname -I | awk '{print $1}')/"
