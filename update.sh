#!/bin/bash
set -e

echo "📦 Wiretide update process started"

PROJECT_DIR="/opt/wiretide"
VENV_DIR="$PROJECT_DIR/venv"
BACKUPS_DIR="$PROJECT_DIR/backups"
CERTS_DIR="/etc/wiretide/certs"
DB_FILE="$PROJECT_DIR/wiretide.db"

cd "$PROJECT_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="$BACKUPS_DIR/backup_$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

# Backup database
if [ -f "$DB_FILE" ]; then
  echo "🗃️  Backing up database to $BACKUP_DIR"
  cp "$DB_FILE" "$BACKUP_DIR/"
else
  echo "⚠️  Database file not found, skipping"
fi

# Backup certs
if [ -d "$CERTS_DIR" ]; then
  echo "🔐 Backing up certificates to $BACKUP_DIR"
  cp -r "$CERTS_DIR" "$BACKUP_DIR/"
else
  echo "⚠️  Certificate directory not found, skipping"
fi

# Ensure git safe.directory
REPO_OWNER=$(stat -c '%U' "$PROJECT_DIR")
CURRENT_USER=$(whoami)
if [ "$REPO_OWNER" != "$CURRENT_USER" ]; then
  echo "⚠️  Git repo is owned by '$REPO_OWNER', but running as '$CURRENT_USER'"
  git config --global --add safe.directory "$PROJECT_DIR"
fi

# Clean repo and pull latest
echo "🧹 Cleaning local repo..."
git reset --hard HEAD
git clean -fd

echo "📥 Pulling latest changes from Git..."
git pull --ff-only

# Ensure virtualenv
if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Creating virtualenv in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  chown -R "$REPO_OWNER":"$REPO_OWNER" "$VENV_DIR"
fi

# Install dependencies
echo "📦 Updating Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install -r requirements.txt
deactivate

# Restart service
echo "🔁 Restarting Wiretide service..."
systemctl restart wiretide.service

echo "✅ Wiretide update completed!"

