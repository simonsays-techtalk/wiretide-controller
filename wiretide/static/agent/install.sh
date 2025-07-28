#!/bin/sh
set -e

echo ">>> Wiretide Agent Installer"

# This value is baked in by the controller installer during its setup
CONTROLLER_URL="__CONTROLLER_URL__"

echo ">> Using controller: $CONTROLLER_URL"

# Store controller URL for the runtime agent
echo "$CONTROLLER_URL" > /etc/wiretide-controller

# Fetch and trust CA cert (ignore TLS just for bootstrap)
CA_PATH="/etc/wiretide-ca.crt"
wget --no-check-certificate -qO "$CA_PATH" "$CONTROLLER_URL/ca.crt" || {
  echo "❌ Failed to download CA cert"
  exit 1
}
chmod 644 "$CA_PATH"
mkdir -p /etc/ssl/certs
cp "$CA_PATH" /etc/ssl/certs/
echo "✅ CA cert installed to $CA_PATH"

# Fetch agent runtime script and init script
echo ">> Downloading agent scripts..."
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

# Enable and start agent
echo ">> Enabling + starting agent"
if command -v /etc/init.d/wiretide >/dev/null; then
  /etc/init.d/wiretide enable
  /etc/init.d/wiretide start
else
  echo "⚠️ Warning: Init script install may have failed"
fi

echo "✅ Wiretide agent installed and running (Controller: $CONTROLLER_URL)"

