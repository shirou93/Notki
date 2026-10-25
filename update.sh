#!/bin/bash
set -e

echo "=========================================================="
echo " Notki Update/Install Script"
echo " This script is recommended for software installation and"
echo " updates. It uses Docker Compose to deploy the application."
echo "=========================================================="

REPO="shirou93/Notki"
REPO_URL="https://github.com/$REPO.git"

echo "Fetching latest tag..."
TAG=$(curl -s "https://api.github.com/repos/$REPO/tags" | grep '"name":' | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$TAG" ]; then
    echo "Error: Could not determine latest tag."
    exit 1
fi
echo "Latest tag is: $TAG"

if [ ! -d ".git" ]; then
    git init
fi

if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "$REPO_URL"
fi

echo "Fetching updates from origin..."
git fetch origin --tags

echo "Checking out tag $TAG..."
git checkout "$TAG"

if [ ! -f ".env" ]; then
    echo "Initializing new .env file..."
    IS_INIT=1
    read -p "Do you want to restore from a backup? (y/N): " -r RESTORE_CHOICE
    if [[ "$RESTORE_CHOICE" =~ ^[TtYy]$ ]]; then
        read -p "Enter the path to the backup file: " -r BACKUP_PATH
        read -p "Enter the backup password: " -r BACKUP_PWD_INPUT
        echo "NOTKI_BACKUP_PASSWORD=\"$BACKUP_PWD_INPUT\"" > .env
    else
        BACKUP_PWD=$(LC_ALL=C tr -dc A-Za-z0-9 </dev/urandom | head -c 128 || true)
        if [ -z "$BACKUP_PWD" ]; then
            BACKUP_PWD=$(openssl rand -hex 64)
        fi
        echo "NOTKI_BACKUP_PASSWORD=\"$BACKUP_PWD\"" > .env
    fi
else
    IS_INIT=0
fi

echo "Building and starting Docker containers..."
docker compose up -d --build

echo "Cleaning up old Docker images..."
docker image prune -f

if [ "$IS_INIT" = "1" ]; then
    if [[ "$RESTORE_CHOICE" =~ ^[TtYy]$ ]]; then
        echo "Restoring backup..."
        # Copy the backup to the container temporarily and restore it
        docker compose exec -T notki sh -c "cat > /tmp/backup.enc" < "$BACKUP_PATH"
        echo "$BACKUP_PWD_INPUT" | docker compose exec -T notki python3 server.py --restore-backup /tmp/backup.enc --yes --backup-password-file -
        docker compose exec -T notki rm -f /tmp/backup.enc
        echo "Backup restored successfully."
    fi
    echo "Fetching setup token..."
    sleep 3
    docker compose logs notki | grep "SETUP TOKEN" || true
fi

echo "Done!"
