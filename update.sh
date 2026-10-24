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
    read -p "Enter backup password (or press Enter to generate randomly): " -r BACKUP_PWD_INPUT

    if [ -z "$BACKUP_PWD_INPUT" ]; then
        # Generate a 32-character random alphanumeric password
        BACKUP_PWD=$(LC_ALL=C tr -dc A-Za-z0-9 </dev/urandom | head -c 32 || true)
        if [ -z "$BACKUP_PWD" ]; then
            BACKUP_PWD=$(openssl rand -hex 16)
        fi
        echo "NOTKI_BACKUP_PASSWORD=\"$BACKUP_PWD\"" > .env
        echo "Generated random NOTKI_BACKUP_PASSWORD in .env"
    else
        echo "NOTKI_BACKUP_PASSWORD=\"$BACKUP_PWD_INPUT\"" > .env
        echo "Saved NOTKI_BACKUP_PASSWORD to .env"
    fi
else
    IS_INIT=0
fi

echo "Building and starting Docker containers..."
docker compose up -d --build

echo "Cleaning up old Docker images..."
docker image prune -f

if [ "$IS_INIT" = "1" ]; then
    echo "Fetching setup token..."
    sleep 3
    docker compose logs notki | grep "SETUP TOKEN" || true
fi

echo "Done!"
