#!/bin/bash
set -e

WIRETIDE_DIR="/opt/wiretide"
CONFIG_DIR="/etc/wiretide"
CERT_DIR="$CONFIG_DIR/certs"
STATIC_DIR="$WIRETIDE_DIR/wiretide/static"
AGENT_DIR="$STATIC_DIR/agent"
DB_FILE="$WIRETIDE_DIR/wiretide.db"
LOG_FILE="/var/log/wiretide.log"
REPO_URL="https://github.com/simonsays-techtalk/wiretide-controller.git"
PYTHON_BIN="/usr/bin/python3"
SERVICE_USER="wiretide"
SERVICE_GROUP="wiretide"
SYSTEMD_SERVICE="/etc/systemd/system/wiretide.service"

echo "[*] Installing Wiretide Controller (dedicated '$SERVICE_USER' user)..."

apt update && apt install -y nginx python3-venv python3-pip sqlite3 openssl git curl

# Maak systeemgebruiker als die nog niet bestaat
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "[*] Creating system user: $SERVICE_USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# Voorbereiden directories
mkdir -p "$WIRETIDE_DIR" "$CERT_DIR" "$STATIC_DIR" "$AGENT_DIR"
chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$WIRETIDE_DIR"
chmod 770 "$WIRETIDE_DIR"  # SQLite moet journal/wal-bestanden kunnen maken
chown -R root:"$SERVICE_GROUP" "$CERT_DIR"
chmod 750 "$CERT_DIR"

cd "$WIRETIDE_DIR"

# Repo ophalen of bijwerken
if [ ! -d "$WIRETIDE_DIR/.git" ]; then
    git clone "$REPO_URL" "$WIRETIDE_DIR"
else
    git pull
fi

# Python virtualenv
if [ ! -d venv ]; then
    $PYTHON_BIN -m venv venv
fi
chown -R "$SERVICE_USER":"$SERVICE_GROUP" "$WIRETIDE_DIR/venv"
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Placeholder logo
if [ ! -f "$STATIC_DIR/wiretide_logo.png" ]; then
    base64 -d > "$STATIC_DIR/wiretide_logo.png" <<'EOF'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAEklEQVR42mP8z8BQDwADgwHBEdkDTwAAAABJRU5ErkJggg==
EOF
    chown "$SERVICE_USER":"$SERVICE_GROUP" "$STATIC_DIR/wiretide_logo.png"
fi

# Database initialiseren
if [ ! -f "$DB_FILE" ]; then
    echo "[*] Creating SQLite database..."
    source venv/bin/activate
    python db_init.py
    deactivate
fi

# Rechten en oude journalbestanden opruimen
chown "$SERVICE_USER":"$SERVICE_GROUP" "$DB_FILE"
chmod 660 "$DB_FILE"
find "$WIRETIDE_DIR" -maxdepth 1 -type f -name "wiretide.db-*" -delete

# Logbestand
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
chown "$SERVICE_USER":"$SERVICE_GROUP" "$LOG_FILE"
chmod 660 "$LOG_FILE"

# API token instellen
API_TOKEN=$(sqlite3 "$DB_FILE" "SELECT token FROM tokens LIMIT 1;" || true)
if [ -z "$API_TOKEN" ]; then
    API_TOKEN=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)
    sqlite3 "$DB_FILE" "INSERT INTO tokens (token, description) VALUES ('$API_TOKEN', 'Default API Token');"
    echo "[*] Generated new API token for /register and /status"
fi

### --- TLS-certificaten ---
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

# Rechten voor certs (service-user mag lezen, Nginx ook)
chown root:"$SERVICE_GROUP" "$CERT_DIR"/*.key "$CERT_DIR"/*.crt
chmod 640 "$CERT_DIR"/*.key
chmod 644 "$CERT_DIR"/*.crt

# CA-cert publiek maken voor agents
cp "$CERT_DIR/wiretide-ca.crt" "$STATIC_DIR/ca.crt"
chown "$SERVICE_USER":"$SERVICE_GROUP" "$STATIC_DIR/ca.crt"

### --- Agent bundling ---
DEBUG_LOG="/tmp/wiretide-debug.log"
cat > "$AGENT_DIR/install.sh" <<EOF
#!/bin/sh
set -e

echo ">>> Wiretide Agent Installer"
CONTROLLER_URL="https://$IP"
echo ">> Using controller: \$CONTROLLER_URL"

# Stop oude agent
if [ -f /etc/init.d/wiretide ]; then
    /etc/init.d/wiretide stop 2>/dev/null || true
    /etc/init.d/wiretide disable 2>/dev/null || true
fi
killall -q wiretide-agent-run 2>/dev/null || true
rm -f /etc/wiretide-agent-run /etc/init.d/wiretide /etc/wiretide-token

# Save controller URL
echo "\$CONTROLLER_URL" > /etc/wiretide-controller

# Fetch CA cert
CA_PATH="/etc/wiretide-ca.crt"
wget --no-check-certificate -qO "\$CA_PATH" "\$CONTROLLER_URL/ca.crt" || {
  echo "❌ Failed to download CA cert"
  exit 1
}
chmod 644 "\$CA_PATH"
mkdir -p /etc/ssl/certs
cp "\$CA_PATH" /etc/ssl/certs/

# Download agent runtime + init script
wget --no-check-certificate -qO /etc/wiretide-agent-run "\$CONTROLLER_URL/static/agent/wiretide-agent-run"
chmod +x /etc/wiretide-agent-run

wget --no-check-certificate -qO /etc/init.d/wiretide "\$CONTROLLER_URL/static/agent/wiretide-init"
chmod +x /etc/init.d/wiretide

# Enable en start agent
/etc/init.d/wiretide enable
/etc/init.d/wiretide start

echo "✅ Wiretide Agent installed (Controller: \$CONTROLLER_URL)"
EOF
chmod +x "$AGENT_DIR/install.sh"

# Agent runtime script
cat > "$AGENT_DIR/wiretide-agent-run" <<'EOF'
#!/bin/sh
CONTROLLER_URL="$(cat /etc/wiretide-controller 2>/dev/null || echo 'https://127.0.0.1')"
CA_CERT="/etc/wiretide-ca.crt"
TOKEN_FILE="/etc/wiretide-token"
INTERVAL=60
POLL_DELAY=10
DEBUG_LOG="/tmp/wiretide-debug.log"

IFACE=""
[ -d /sys/class/net/br-lan ] && IFACE="br-lan"
[ -z "$IFACE" ] && IFACE="$(ip route | awk '/default/ {print $5}' | head -n1)"
[ -z "$IFACE" ] && IFACE="$(ip -o link show | awk -F': ' '/state UP/ && $2 != "lo" {print $2; exit}')"
MAC="$(ip link show "$IFACE" 2>/dev/null | awk '/ether/ {print $2}')"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$DEBUG_LOG"; }

fetch_token() {
    log "Requesting token for MAC: $MAC"
    TOKEN=$(curl --cacert "$CA_CERT" -sSf -X GET "$CONTROLLER_URL/token/$MAC" || echo "")
    if [ -n "$TOKEN" ]; then
        echo "$TOKEN" > "$TOKEN_FILE"
        log "Received token and saved"
    else
        log "Token fetch failed, waiting for approval"
    fi
}

status_update() {
    [ ! -f "$TOKEN_FILE" ] && return 1
    TOKEN="$(cat "$TOKEN_FILE")"
    RESPONSE=$(curl --cacert "$CA_CERT" -s -w "%{http_code}" -o /dev/null \
        -H "Authorization: Bearer $TOKEN" \
        "$CONTROLLER_URL/status/$MAC")
    if [ "$RESPONSE" -eq 401 ]; then
        log "Token expired, refetching..."
        rm -f "$TOKEN_FILE"
        fetch_token
    fi
}

log "Starting Wiretide agent (Controller: $CONTROLLER_URL, MAC: $MAC)"
while [ ! -f "$TOKEN_FILE" ]; do
    fetch_token
    [ -f "$TOKEN_FILE" ] || sleep "$POLL_DELAY"
done
while true; do
    status_update
    sleep "$INTERVAL"
done
EOF
chmod +x "$AGENT_DIR/wiretide-agent-run"

# Agent init script
cat > "$AGENT_DIR/wiretide-init" <<'EOF'
#!/bin/sh /etc/rc.common
START=99
start() { /etc/wiretide-agent-run & }
stop() { kill "$(pgrep -f wiretide-agent-run)" 2>/dev/null; }
EOF
chmod +x "$AGENT_DIR/wiretide-init"

### --- Nginx configuratie ---
cat > /etc/nginx/sites-available/wiretide <<'EOF'
server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/wiretide/certs/wiretide.crt;
    ssl_certificate_key /etc/wiretide/certs/wiretide.key;

    location /ca.crt {
        alias /opt/wiretide/wiretide/static/ca.crt;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name _;

    location /static/agent/ {
        alias /opt/wiretide/wiretide/static/agent/;
        autoindex on;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
EOF
ln -sf /etc/nginx/sites-available/wiretide /etc/nginx/sites-enabled/wiretide
rm -f /etc/nginx/sites-enabled/default
systemctl restart nginx

### --- Systemd service voor Wiretide ---
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
Environment="PATH=$WIRETIDE_DIR/venv/bin"
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now wiretide

echo "==========================================="
echo " Wiretide Controller Installed"
echo "-------------------------------------------"
echo "Running as user: $SERVICE_USER"
echo "Access:   https://$IP/"
echo "Username: admin"
echo "Password: wiretide"
echo "API Token (for agents): $API_TOKEN"
echo "CA Download: https://$IP/ca.crt"
echo "Agent Installer: http://$IP/static/agent/install.sh"
echo "==========================================="

