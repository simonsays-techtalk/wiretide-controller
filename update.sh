#!/bin/bash
set -e

echo "📦 Wiretide update process started"


PROJECT_DIR="/opt/wiretide"
cd "$PROJECT_DIR"


TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="$PROJECT_DIR/backups/backup_$TIMESTAMP"
mkdir -p "$BACKUP_DIR"


echo "🔐 Database and certificates are being backupped to $BACKUP_DIR"
cp wiretide.db "$BACKUP_DIR/"
cp -r /etc/wiretide/certs "$BACKUP_DIR/"


echo "📥 Execute Git pull..."
git pull --ff-only


if [ -f "requirements.txt" ]; then
  echo "📦 Python dependencies update..."
  pip install -r requirements.txt
fi


echo "🔁 Wiretide service restart..."
systemctl restart wiretide.service

echo "✅ Update completed!"

