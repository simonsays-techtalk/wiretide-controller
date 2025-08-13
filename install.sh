#!/bin/bash
set -e

# Set default branch if not explicitly passed
BRANCH="${WIRETIDE_BRANCH:-beta}"
echo "[*] Installing from branch: $BRANCH"
if [ "$BRANCH" = "main" ]; then
    echo "==> PRODUCTION INSTALL"
    WIRETIDE_DIR="/opt/wiretide"

    LOG_FILE="/var/log/wiretide.log"
    SYSTEMD_SERVICE="/etc/systemd/system/wiretide.service"
else
    echo "==> DEVELOPMENT INSTALL — beta branch"
    WIRETIDE_DIR="/opt/wiretide-beta"
    LOG_FILE="/var/log/wiretide-beta.log"
    SYSTEMD_SERVICE="/etc/systemd/system/wiretide-beta.service"
fi

CONFIG_DIR="/etc/wiretide"
CERT_DIR="$WIRETIDE_DIR/certs"
STATIC_DIR="$WIRETIDE_DIR/wiretide/static"
AGENT_DIR="$STATIC_DIR/agent"
DB_FILE="$WIRETIDE_DIR/wiretide.db"
REPO_URL="https://github.com/simonsays-techtalk/wiretide-controller.git"
PYTHON_BIN="/usr/bin/python3"
SERVICE_USER="wiretide"
SERVICE_GROUP="wiretide"

#----------------------------------------
echo "[*] Installing Wiretide Controller (dedicated '$SERVICE_USER' user, clean install)..."

apt update && apt install -y nginx python3-venv python3-pip sqlite3 openssl git curl

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "[*] Creating system user: $SERVICE_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [ -d "$WIRETIDE_DIR" ]; then
    echo "[*] Removing existing installation at $WIRETIDE_DIR"
    rm -rf "$WIRETIDE_DIR"
fi

git clone --branch "$BRANCH" "$REPO_URL" "$WIRETIDE_DIR"

mkdir -p "$CERT_DIR" "$STATIC_DIR" "$AGENT_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$WIRETIDE_DIR"
chmod 770 "$WIRETIDE_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$CERT_DIR"
chmod 750 "$CERT_DIR"

cd "$WIRETIDE_DIR"

if [ ! -d venv ]; then
    $PYTHON_BIN -m venv venv
fi
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$WIRETIDE_DIR/venv"
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

if [ ! -f "$STATIC_DIR/wiretide_logo.png" ]; then
    base64 -d > "$STATIC_DIR/wiretide_logo.png" <<'EOF'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEklEQVR42mP8z8BQDwADgwHBEdkDTwAAAABJRU5ErkJggg==
EOF
    chown "$SERVICE_USER:$SERVICE_GROUP" "$STATIC_DIR/wiretide_logo.png"
fi

if [ ! -f "$DB_FILE" ]; then
    echo "[*] Creating SQLite database..."
    source venv/bin/activate
    sudo -u "$SERVICE_USER" env PATH="$WIRETIDE_DIR/venv/bin:$PATH" WIRETIDE_BRANCH="$BRANCH" python db_init.py
    deactivate
fi

chmod 660 "$DB_FILE"
chown "$SERVICE_USER:$SERVICE_GROUP" "$DB_FILE"
chmod 770 "$WIRETIDE_DIR"

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_FILE"
chmod 660 "$LOG_FILE"

API_TOKEN=$(sqlite3 "$DB_FILE" "SELECT token FROM tokens LIMIT 1;" || true)
if [ -z "$API_TOKEN" ]; then
    API_TOKEN=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)
    sqlite3 "$DB_FILE" "INSERT INTO tokens (token, description) VALUES ('$API_TOKEN', 'Default API Token');"
    echo "[*] Generated new API token for /register and /status"
fi

#----------------------------------------
echo "[*] Setting up CA and SAN-enabled TLS cert..."
IP=$(hostname -I | awk '{print $1}')
if [ ! -f "$CERT_DIR/wiretide-ca.crt" ]; then
    openssl genrsa -out "$CERT_DIR/wiretide-ca.key" 4096
    openssl req -x509 -new -nodes -key "$CERT_DIR/wiretide-ca.key" -sha256 -days 3650 \
      -subj "/CN=Wiretide Root CA" -out "$CERT_DIR/wiretide-ca.crt"
fi

cat > "$CERT_DIR/openssl-san.cnf" <<EOF
[req]
default_bits = 4096
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = wiretide

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = wiretide
IP.1 = $IP
EOF

openssl genrsa -out "$CERT_DIR/wiretide.key" 4096
openssl req -new -key "$CERT_DIR/wiretide.key" -out "$CERT_DIR/wiretide.csr" -config "$CERT_DIR/openssl-san.cnf"
openssl x509 -req -in "$CERT_DIR/wiretide.csr" -CA "$CERT_DIR/wiretide-ca.crt" -CAkey "$CERT_DIR/wiretide-ca.key" \
  -CAcreateserial -out "$CERT_DIR/wiretide.crt" -days 825 -sha256 -extensions v3_req -extfile "$CERT_DIR/openssl-san.cnf"

chown "$SERVICE_USER:$SERVICE_GROUP" "$CERT_DIR"/*.key "$CERT_DIR"/*.crt
chmod 640 "$CERT_DIR"/*.key
chmod 644 "$CERT_DIR"/*.crt

cp "$CERT_DIR/wiretide-ca.crt" "$STATIC_DIR/ca.crt"
chown "$SERVICE_USER:$SERVICE_GROUP" "$STATIC_DIR/ca.crt"
chmod o+x /opt "$WIRETIDE_DIR" "$STATIC_DIR"

#----------------------------------------
echo "[*] Preparing agent static files..."

if [ ! -f "$AGENT_DIR/install.template.sh" ]; then
    echo "❌ Missing required file: $AGENT_DIR/install.template.sh"
    exit 1
fi

sed "s|__CONTROLLER_URL__|https://$IP|g" "$AGENT_DIR/install.template.sh" > "$AGENT_DIR/install.sh"
chmod +x "$AGENT_DIR/install.sh" "$AGENT_DIR/wiretide-agent-run" "$AGENT_DIR/wiretide-init"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$AGENT_DIR"

#----------------------------------------
cat > /etc/nginx/sites-available/wiretide <<EOF
server {
    listen 443 ssl;
    server_name _;

    ssl_certificate $CERT_DIR/wiretide.crt;
    ssl_certificate_key $CERT_DIR/wiretide.key;

    location /ca.crt {
        alias $STATIC_DIR/ca.crt;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

server {
    listen 80;
    server_name _;

    location /static/agent/ {
        alias $AGENT_DIR/;
        autoindex on;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}
EOF

ln -sf /etc/nginx/sites-available/wiretide /etc/nginx/sites-enabled/wiretide
rm -f /etc/nginx/sites-enabled/default
systemctl restart nginx

#----------------------------------------
cat > "$SYSTEMD_SERVICE" <<EOF
[Unit]
Description=Wiretide Controller
After=network.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$WIRETIDE_DIR
ExecStart=/usr/bin/env uvicorn wiretide.main:app --host 127.0.0.1 --port 8000
Restart=always
Environment="PATH=$WIRETIDE_DIR/venv/bin:/usr/bin:/bin"
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=multi-user.target
EOF

echo "[*] Granting passwordless sudo for restarting Wiretide service"
echo "$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart wiretide.service" > /etc/sudoers.d/wiretide-restart
chmod 440 /etc/sudoers.d/wiretide-restart

systemctl daemon-reload
systemctl enable --now wiretide

#----------------------------------------
echo "==========================================="
echo " Wiretide Controller Installed (Clean)"
echo "-------------------------------------------"
echo "Running as user: $SERVICE_USER"
echo "Access:   https://$IP/"
echo "Username: admin"
echo "Password: wiretide"
echo "API Token (for agents): $API_TOKEN"
echo "CA Download: https://$IP/ca.crt"
echo "Agent Installer: http://$IP/static/agent/install.sh"
echo "==========================================="
