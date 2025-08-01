#!/bin/bash
set -e

echo "📦 Wiretide update process started"

PROJECT_DIR="/opt/wiretide"
VENV_DIR="$PROJECT_DIR/venv"
BACKUPS_DIR="$PROJECT_DIR/backups"
CERTS_DIR="/etc/wiretide/certs"
DB_FILE="$PROJECT_DIR/wiretide.db"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="$BACKUPS_DIR/backup_$TIMESTAMP"

cd "$PROJECT_DIR"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup database
if [ -f "$DB_FILE" ]; then
  echo "🗃️  Backing up database to $BACKUP_DIR"
  cp "$DB_FILE" "$BACKUP_DIR/"
else
  echo "⚠️  Database file not found, skipping DB backup"
fi

# Backup TLS certificates
if [ -d "$CERTS_DIR" ]; then
  echo "🔐 Backing up certificates to $BACKUP_DIR"
  cp -r "$CERTS_DIR" "$BACKUP_DIR/"
else
  echo "⚠️  Certificate directory not found, skipping cert backup"
fi

# Ensure git safe.directory (in case running under another user)
REPO_OWNER=$(stat -c '%U' "$PROJECT_DIR")
CURRENT_USER=$(whoami)
if [ "$REPO_OWNER" != "$CURRENT_USER" ]; then
  echo "⚠️  Git repo is owned by '$REPO_OWNER', running as '$CURRENT_USER'"
  git config --global --add safe.directory "$PROJECT_DIR"
fi

# Clean and pull latest changes
echo "🧹 Cleaning local repository..."
git reset --hard HEAD
git clean -fd

echo "📥 Pulling latest changes from Git (beta branch)..."
git pull --ff-only

# Ensure virtualenv exists
if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Creating Python virtual environment"
  python3 -m venv "$VENV_DIR"
  chown -R "$REPO_OWNER":"$REPO_OWNER" "$VENV_DIR"
fi

# Install/update dependencies
echo "📦 Installing/updating Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

# Apply database schema updates
echo "🛠️  Applying database migrations..."
python db_init.py
deactivate

# Restart controller service
echo "🔁 Restarting Wiretide service..."
systemctl restart wiretide.service

echo "✅ Wiretide update completed successfully!"

