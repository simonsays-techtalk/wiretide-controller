#!/bin/sh
set -e

echo ">>> Wiretide Agent Installer"

# Prompt for controller URL
printf "Enter Wiretide controller URL (e.g. https://wiretide.autohome.local): "
read CONTROLLER_URL

# Strip protocol to get hostname (used for CA fetch)
CONTROLLER_HOST="$(echo "$CONTROLLER_URL" | sed -E 's|https?://||' | cut -d/ -f1)"

if [ -z "$CONTROLLER_URL" ] || [ -z "$CONTROLLER_HOST" ]; then
  echo "❌ Error: Controller URL is invalid"
  exit 1
fi

echo ">> Using controller: $CONTROLLER_URL"
echo ">> Resolving and downloading CA cert from: http://$CONTROLLER_HOST/wiretide-ca.crt"

# Fetch CA cert (bootstrap trust)
CA_PATH="/etc/wiretide-ca.crt"
wget -qO "$CA_PATH" "http://$CONTROLLER_HOST/wiretide-ca.crt" || {
  echo "❌ Failed to download CA cert over HTTP"
  exit 1
}

if [ ! -s "$CA_PATH" ]; then
  echo "❌ Downloaded CA cert is empty"
  exit 1
fi

chmod 644 "$CA_PATH"
echo "✅ CA cert saved to $CA_PATH"

# Fetch agent script securely
echo ">> Downloading agent..."
curl --cacert "$CA_PATH" -sSf "$CONTROLLER_URL/wiretide-agent-run" -o /etc/wiretide-agent-run || {
  echo "❌ Failed to download wiretide-agent-run"
  exit 1
}
chmod +x /etc/wiretide-agent-run

# Inject controller URL
sed -i "s|^CONTROLLER_URL=.*|CONTROLLER_URL=\"$CONTROLLER_URL\"|" /etc/wiretide-agent-run

# Fetch init script
echo ">> Downloading init script..."
curl --cacert "$CA_PATH" -sSf "$CONTROLLER_URL/wiretide-init" -o /etc/init.d/wiretide || {
  echo "❌ Failed to download wiretide-init"
  exit 1
}
chmod +x /etc/init.d/wiretide

# Enable + start
echo ">> Enabling + starting agent"
if command -v /etc/init.d/wiretide >/dev/null; then
  /etc/init.d/wiretide enable
  /etc/init.d/wiretide start
else
  echo "⚠️ Warning: Init script install may have failed"
fi

echo "✅ Wiretide agent installed and running securely."
