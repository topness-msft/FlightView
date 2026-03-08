#!/bin/bash
# FlightView — Raspberry Pi Deployment Script
# Run this on the Pi after cloning the repo:
#   chmod +x deploy-pi.sh && ./deploy-pi.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/src"
SERVICE_NAME="flightview"
USER="${SUDO_USER:-$USER}"
HOME_DIR=$(eval echo "~$USER")

echo "╔══════════════════════════════════════╗"
echo "║     FlightView Pi Deployment         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. System dependencies ─────────────────
echo "→ Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv chromium-browser unclutter

# ── 2. Python virtual environment ──────────
echo "→ Setting up Python environment..."
if [ ! -d "$SCRIPT_DIR/venv" ]; then
    python3 -m venv "$SCRIPT_DIR/venv"
fi
source "$SCRIPT_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"

# ── 3. Configure .env ─────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "→ Creating .env from example..."
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo ""
    echo "⚠  Edit .env with your settings:"
    echo "   nano $SCRIPT_DIR/.env"
    echo ""
    echo "   Required: HOME_LAT, HOME_LON"
    echo "   Optional: ADSBX_API_KEY (FlightAware key)"
    echo ""
    read -p "   Press Enter to edit now, or Ctrl+C to skip..." _
    nano "$SCRIPT_DIR/.env"
else
    echo "→ .env already exists, skipping..."
fi

# ── 4. Systemd service ────────────────────
echo "→ Installing systemd service..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=FlightView Aircraft Tracker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$SCRIPT_DIR/venv/bin/python3 $APP_DIR/app.py
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5
User=$USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo "→ Service installed and started"

# ── 5. Chromium kiosk autostart ───────────
echo "→ Configuring kiosk mode..."
AUTOSTART_DIR="$HOME_DIR/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/flightview-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FlightView Kiosk
Comment=Launch FlightView in fullscreen kiosk mode
Exec=bash -c 'sleep 5 && chromium-browser --kiosk --noerrdialogs --disable-infobars --disable-translate --no-first-run --fast --fast-start --disable-features=TranslateUI --disk-cache-dir=/dev/null http://localhost:5000'
X-GNOME-Autostart-enabled=true
EOF

# Hide cursor after 3 seconds of inactivity
cat > "$AUTOSTART_DIR/unclutter.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Unclutter
Exec=unclutter -idle 3
X-GNOME-Autostart-enabled=true
EOF

# Disable screen blanking
if ! grep -q "xserver-command" /etc/lightdm/lightdm.conf 2>/dev/null; then
    sudo mkdir -p /etc/lightdm
    sudo tee -a /etc/lightdm/lightdm.conf > /dev/null <<EOF2

[Seat:*]
xserver-command=X -s 0 -dpms
EOF2
    echo "→ Screen blanking disabled"
fi

# ── 6. Verify ─────────────────────────────
echo ""
echo "→ Checking service status..."
sleep 2
if systemctl is-active --quiet ${SERVICE_NAME}; then
    echo "✓ FlightView service is running"
else
    echo "✗ Service failed to start. Check: sudo journalctl -u ${SERVICE_NAME} -n 20"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║     Deployment Complete!             ║"
echo "╠══════════════════════════════════════╣"
echo "║  Web UI:  http://localhost:5000      ║"
echo "║  Service: sudo systemctl status $SERVICE_NAME ║"
echo "║  Logs:    sudo journalctl -u $SERVICE_NAME -f ║"
echo "║  Config:  nano $SCRIPT_DIR/.env      ║"
echo "║                                      ║"
echo "║  Reboot to start kiosk mode:         ║"
echo "║    sudo reboot                       ║"
echo "╚══════════════════════════════════════╝"
