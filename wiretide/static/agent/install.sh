#!/bin/sh
set -e

echo ">>> Wiretide Agent Installer"

# This placeholder gets replaced by the controller installer
CONTROLLER_URL="__CONTROLLER_URL__"
echo ">> Using controller: $CONTROLLER_URL"

# --- Ensure curl is installed ---
if ! command -v curl >/dev/null 2>&1; then
    echo ">> curl not found, attempting to install..."
    opkg update
    opkg install curl || {
        echo "❌ Failed to install curl"
        exit 1
    }
    echo "✅ curl installed"
fi

# --- Clean up any old agent first ---
if [ -f /etc/init.d/wiretide ]; then
    echo ">> Stopping and removing old Wiretide agent..."
    /etc/init.d/wiretide stop 2>/dev/null || true
    /etc/init.d/wiretide disable 2>/dev/null || true
fi
killall -q wiretide-agent-run 2>/dev/null || true
rm -f /etc/wiretide-agent-run /etc/init.d/wiretide /etc/wiretide-token

# --- Save controller URL for runtime use ---
echo "$CONTROLLER_URL" > /etc/wiretide-controller

# --- Fetch and trust the CA certificate ---
CA_PATH="/etc/wiretide-ca.crt"
echo ">> Downloading CA certificate..."
wget --no-check-certificate -qO "$CA_PATH" "$CONTROLLER_URL/ca.crt" || {
  echo "❌ Failed to download CA cert"
  exit 1
}
chmod 644 "$CA_PATH"
mkdir -p /etc/ssl/certs
cp "$CA_PATH" /etc/ssl/certs/
echo "✅ CA certificate installed"

# --- Fetch latest agent scripts ---
echo ">> Downloading agent runtime and init scripts..."
wget --no-check-certificate -qO /etc/wiretide-agent-run "$CONTROLLER_URL/static/agent/wiretide-agent-run" || {
  echo "❌ Failed to download wiretide-agent-run"
  exit 1
}
chmod +x /etc/wiretide-agent-run

wget --no-check-certificate -qO /etc/init.d/wiretide "$CONTROLLER_URL/static/agent/wiretide-init" || {
  echo "❌ Failed to download wiretide-init"
  exit 1
}
chmod +x /etc/init.d/wiretide

# --- Enable and start agent ---
/etc/init.d/wiretide enable
/etc/init.d/wiretide start

echo "✅ Wiretide Agent installed and running (Controller: $CONTROLLER_URL)"

