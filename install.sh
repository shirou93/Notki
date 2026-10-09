#!/bin/bash
set -e

echo "Installing Notki..."

# 1. Install python3 if not present
if ! command -v python3 &> /dev/null; then
    echo "Python3 not found. Installing..."
    if [ -x "$(command -v apt)" ]; then
        apt update && apt install -y python3 git
    elif [ -x "$(command -v dnf)" ]; then
        dnf install -y python3 git
    elif [ -x "$(command -v pacman)" ]; then
        pacman -Sy --noconfirm python3 git
    else
        echo "Please install python3 and git manually."
        exit 1
    fi
fi

# 2. Clone repository to /opt/notki
if [ -d "/opt/notki" ]; then
    echo "/opt/notki already exists. Updating..."
    cd /opt/notki && git pull
else
    echo "Cloning repository to /opt/notki..."
    git clone https://github.com/shirou93/Notki /opt/notki
fi

# 3. Create dedicated notki system user
if ! id "notki" &>/dev/null; then
    echo "Creating 'notki' system user..."
    useradd -r -s /bin/false notki
fi

mkdir -p /opt/notki/data
chown -R notki:notki /opt/notki

# 4. Set up systemd service
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
Environment=NOTKI_COOKIE_SECURE=0
Environment=NOTKI_PUBLIC_HTTPS=0
ExecStart=/usr/bin/python3 /opt/notki/server.py
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/notki/data

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# 5. Enable and start the service
systemctl daemon-reload
systemctl enable notki.service
systemctl restart notki.service

echo "Notki is installed and running on http://127.0.0.1:8000"
echo "You can view logs with: journalctl -fu notki"
