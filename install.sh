#!/bin/bash
set -e

WIRETIDE_DIR="/opt/wiretide"
CERT_DIR="/etc/wiretide/certs"
STATIC_DIR="$WIRETIDE_DIR/wiretide/static"
AGENT_DIR="$STATIC_DIR/agent"
DB_FILE="$WIRETIDE_DIR/wiretide.db"
LOG_FILE="/var/log/wiretide.log"
REPO_URL="https://github.com/simonsays-techtalk/wiretide-controller.git"
PYTHON_BIN="/usr/bin/python3"

echo "[*] Installing Wiretide Controller with CA support..."

# Install system dependencies
apt update && apt install -y nginx python3-venv python3-pip sqlite3 openssl git curl

git config --global --add safe.directory "$WIRETIDE_DIR" || true

# Clone or update repo
mkdir -p "$WIRETIDE_DIR" "$CERT_DIR"
if [ ! -d "$WIRETIDE_DIR/.git" ]; then
    git clone "$REPO_URL" "$WIRETIDE_DIR"
else
    cd "$WIRETIDE_DIR"
    git pull
fi
chown -R www-data:www-data "$WIRETIDE_DIR"

cd "$WIRETIDE_DIR"

# Virtual environment
if [ ! -d venv ]; then
    $PYTHON_BIN -m venv venv
fi
chown -R www-data:www-data "$WIRETIDE_DIR/venv"
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

mkdir -p "$STATIC_DIR" "$AGENT_DIR"
chown -R www-data:www-data "$STATIC_DIR"

# Placeholder logo
if [ ! -f "$STATIC_DIR/wiretide_logo.png" ]; then
    base64 -d > "$STATIC_DIR/wiretide_logo.png" <<'EOF'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEklEQVR42mP8z8BQDwADgwHBEdkDTwAAAABJRU5ErkJggg==
EOF
    chown www-data:www-data "$STATIC_DIR/wiretide_logo.png"
fi

# Database init
if [ ! -f "$DB_FILE" ]; then
    echo "[*] Creating SQLite database..."
    source venv/bin/activate
    python db_init.py
    deactivate
fi
DB_DIR=$(dirname "$DB_FILE")
chown -R www-data:www-data "$DB_FILE" "$DB_DIR"
chmod -R 775 "$DB_DIR"
chmod 664 "$DB_FILE"

# Log file
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chown www-data:www-data "$LOG_FILE"
chmod 664 "$LOG_FILE"

# API token
API_TOKEN=$(sqlite3 "$DB_FILE" "SELECT token FROM tokens LIMIT 1;" || true)
if [ -z "$API_TOKEN" ]; then
    API_TOKEN=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)
    sqlite3 "$DB_FILE" "INSERT INTO tokens (token, description) VALUES ('$API_TOKEN', 'Default API Token');"
    echo "[*] Generated new API token for /register and /status"
fi

### --- CA & CERT SETUP ---
echo "[*] Setting up CA and server TLS cert..."
# Create root CA if missing
if [ ! -f "$CERT_DIR/wiretide-ca.crt" ]; then
    openssl genrsa -out "$CERT_DIR/wiretide-ca.key" 4096
    openssl req -x509 -new -nodes -key "$CERT_DIR/wiretide-ca.key" -sha256 -days 3650 \
      -subj "/CN=Wiretide Root CA" -out "$CERT_DIR/wiretide-ca.crt"
fi

# Always create a new server cert signed by the CA
openssl genrsa -out "$CERT_DIR/wiretide.key" 4096
openssl req -new -key "$CERT_DIR/wiretide.key" -subj "/CN=wiretide" -out "$CERT_DIR/wiretide.csr"
openssl x509 -req -in "$CERT_DIR/wiretide.csr" -CA "$CERT_DIR/wiretide-ca.crt" -CAkey "$CERT_DIR/wiretide-ca.key" \
  -CAcreateserial -out "$CERT_DIR/wiretide.crt" -days 825 -sha256

# Make the CA cert available to agents
cp "$CERT_DIR/wiretide-ca.crt" "$STATIC_DIR/ca.crt"
chown www-data:www-data "$STATIC_DIR/ca.crt"

### --- GENERATE AGENT INSTALLER WITH CONTROLLER IP ---
IP=$(hostname -I | awk '{print $1}')
cat > "$AGENT_DIR/install.sh" <<EOF
#!/bin/sh
set -e

CONTROLLER_URL="https://$IP"

echo "[*] Installing Wiretide Agent for controller at \$CONTROLLER_URL..."

# Download and trust CA cert
wget --no-check-certificate -O /etc/wiretide-ca.crt "\$CONTROLLER_URL/ca.crt"
mkdir -p /etc/ssl/certs
cp /etc/wiretide-ca.crt /etc/ssl/certs/
echo "[*] CA certificate installed."

# Fetch agent files
wget --no-check-certificate -O /etc/wiretide-agent-run "\$CONTROLLER_URL/static/agent/wiretide-agent-run"
wget --no-check-certificate -O /etc/init.d/wiretide "\$CONTROLLER_URL/static/agent/wiretide-init"
chmod +x /etc/wiretide-agent-run /etc/init.d/wiretide

# Enable service
/etc/init.d/wiretide enable
/etc/init.d/wiretide start

echo "[*] Wiretide Agent installed and running (Controller: \$CONTROLLER_URL)."
EOF
chmod +x "$AGENT_DIR/install.sh"
chown www-data:www-data "$AGENT_DIR/install.sh"

# Systemd service
cp wiretide.service /etc/systemd/system/wiretide.service
systemctl daemon-reload
systemctl enable --now wiretide.service

# Nginx proxy
cp nginx.conf /etc/nginx/sites-available/wiretide
ln -sf /etc/nginx/sites-available/wiretide /etc/nginx/sites-enabled/wiretide
systemctl restart nginx

# Sudo permissions for www-data
sudo bash -c 'cat >/etc/sudoers.d/wiretide' <<'EOF'
www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart wiretide.service
EOF
chmod 440 /etc/sudoers.d/wiretide

# Health check
sleep 3
if ! curl -sk https://127.0.0.1/ > /dev/null; then
    echo "[!] Wiretide may not be running. Logs:"
    journalctl -u wiretide --no-pager -n 50
else
    echo "[*] Wiretide is up and reachable locally."
fi

echo "==========================================="
echo " Wiretide Controller Installed Successfully"
echo "-------------------------------------------"
echo "Access:   https://$IP/"
echo "Username: admin"
echo "Password: wiretide"
echo "API Token (for agents): $API_TOKEN"
echo "CA Download: https://$IP/ca.crt"
echo "Agent Installer (Has controller IP set):"
echo "  https://$IP/static/agent/install.sh"
echo "==========================================="

