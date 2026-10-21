#!/bin/bash
set -euo pipefail

NOTKI_INSTALL_REF="${NOTKI_INSTALL_REF:-v0.1.6.2}"

echo "Installing Notki..."

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root." >&2
    exit 1
fi

# 1. Install Python, pip and the tools needed to fetch a pinned release.
if ! command -v python3 >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1; then
    echo "Installing python3, pip and git..."
    if command -v apt >/dev/null 2>&1; then
        apt update && apt install -y python3 python3-pip git ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip git ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Sy --noconfirm python3 python-pip git ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip git ca-certificates
    else
        echo "Please install python3, pip, git and CA certificates manually." >&2
        exit 1
    fi
fi

# 2. Clone or update the pinned release instead of tracking a moving branch.
if [ -d "/opt/notki/.git" ]; then
    echo "Updating /opt/notki to ${NOTKI_INSTALL_REF}..."
    git -C /opt/notki fetch --tags --force
    git -C /opt/notki checkout --force "${NOTKI_INSTALL_REF}"
elif [ -d "/opt/notki" ]; then
    echo "/opt/notki exists but is not a git checkout; refusing to overwrite it." >&2
    exit 1
else
    echo "Cloning ${NOTKI_INSTALL_REF} to /opt/notki..."
    git clone --branch "${NOTKI_INSTALL_REF}" --depth 1 https://github.com/shirou93/Notki /opt/notki
fi

# 3. Install pinned, binary-only Python dependencies.
echo "Installing pinned Python dependencies..."
python3 -m pip install --no-cache-dir --only-binary=:all: -r /opt/notki/requirements.txt

# 4. Create a dedicated system user.
if ! id "notki" >/dev/null 2>&1; then
    echo "Creating 'notki' system user..."
    useradd -r -s /bin/false notki
fi

mkdir -p /opt/notki/data/backups
chown -R notki:notki /opt/notki/data
chmod 700 /opt/notki/data
chown notki:notki /opt/notki

# 5. Set up the systemd service with conservative sandboxing.
echo "Setting up systemd service..."
cat << 'SERVICE_EOF' > /etc/systemd/system/notki.service
[Unit]
Description=Notki private notes app
After=network.target

[Service]
Type=simple
User=notki
Group=notki
WorkingDirectory=/opt/notki
Environment=NOTKI_HOST=127.0.0.1
Environment=NOTKI_PORT=8000
Environment=NOTKI_TRUST_PROXY=127.0.0.1/32
Environment=NOTKI_PUBLIC_HTTPS=0
ExecStart=/usr/bin/python3 /opt/notki/server.py
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=/opt/notki/data

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable notki.service
systemctl restart notki.service

echo "Notki is running on http://127.0.0.1:8000"
echo "Read the setup token with: journalctl -u notki | grep 'SETUP TOKEN'"
echo "Then open /setup and paste the token."
