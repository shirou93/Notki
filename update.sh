#!/bin/bash
set -euo pipefail

echo "Fetching the latest tag for Notki..."
TAG=$(curl -s https://api.github.com/repos/shirou93/Notki/tags | grep '"name":' | head -n 1 | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$TAG" ]; then
  echo "Failed to fetch the latest tag."
  kill -INT $$
fi

echo "Latest tag found: $TAG"

if [ ! -d ".git" ]; then
    echo "No existing installation found. Setting up repository..."
    git init
    git remote add origin https://github.com/shirou93/Notki.git
    git fetch origin --tags
    git checkout -f "$TAG"
else
    echo "Fetching git tags..."
    git fetch --tags
    echo "Checking out tag: $TAG"
    git checkout -f "$TAG"
fi

echo "Rebuilding docker image and restarting container..."
docker compose up -d --build

echo "Update/Installation to $TAG completed successfully."
