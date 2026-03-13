#!/bin/bash
# FlightView — Raspberry Pi Deployment Script
# Run this on the Pi after copying files:
#   chmod +x deploy-pi.sh && ./deploy-pi.sh
#
# Options:
#   --no-rtlsdr    Skip RTL-SDR / readsb setup
#   --no-kiosk     Skip Chromium kiosk setup (headless server only)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/src"
SERVICE_NAME="flightview"
USER="${SUDO_USER:-$USER}"
HOME_DIR=$(eval echo "~$USER")

# Parse flags
INSTALL_RTLSDR=true
INSTALL_KIOSK=true
for arg in "$@"; do
    case "$arg" in
        --no-rtlsdr) INSTALL_RTLSDR=false ;;
        --no-kiosk)  INSTALL_KIOSK=false ;;
    esac
done

echo "╔══════════════════════════════════════╗"
echo "║     FlightView Pi Deployment         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. System dependencies ─────────────────
echo "→ Installing system dependencies..."
sudo apt-get update -qq
PACKAGES="python3 python3-pip python3-venv"
if $INSTALL_KIOSK; then
    PACKAGES="$PACKAGES chromium-browser unclutter"
fi
sudo apt-get install -y -qq $PACKAGES

# ── 1b. RTL-SDR / readsb ──────────────────
if $INSTALL_RTLSDR; then
    if systemctl is-active --quiet readsb 2>/dev/null; then
        echo "→ readsb is already running, skipping install"
    else
        echo ""
        echo "┌──────────────────────────────────────┐"
        echo "│  RTL-SDR / readsb Setup              │"
        echo "└──────────────────────────────────────┘"
        echo ""

        # Build dependencies
        echo "→ Installing RTL-SDR and build dependencies..."
        sudo apt-get install -y -qq \
            rtl-sdr librtlsdr-dev librtlsdr0 \
            build-essential debhelper pkg-config \
            libncurses-dev zlib1g-dev libzstd-dev help2man

        # Blacklist the DVB-T kernel driver so it doesn't grab the dongle
        if ! grep -q "blacklist dvb_usb_rtl28xxu" /etc/modprobe.d/blacklist-rtlsdr.conf 2>/dev/null; then
            echo "→ Blacklisting DVB-T kernel driver..."
            sudo tee /etc/modprobe.d/blacklist-rtlsdr.conf > /dev/null <<BLACKLIST
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
BLACKLIST
            echo "  (reboot required for driver blacklist to take effect)"
        fi

        # Clone and build readsb
        READSB_BUILD="/tmp/readsb-build"
        rm -rf "$READSB_BUILD"
        echo "→ Cloning readsb..."
        git clone --depth 1 https://github.com/wiedehopf/readsb.git "$READSB_BUILD"
        cd "$READSB_BUILD"

        echo "→ Building readsb (this takes a few minutes on a Pi)..."
        dpkg-buildpackage -b -Jauto --no-sign 2>&1 | tail -5
        cd /tmp

        echo "→ Installing readsb package..."
        sudo dpkg -i readsb_*.deb || sudo apt-get install -f -y -qq
        rm -rf "$READSB_BUILD" /tmp/readsb_*.deb /tmp/readsb-dbgsym_*.deb 2>/dev/null

        cd "$SCRIPT_DIR"

        # Configure readsb: RTL-SDR input, network API on port 8080
        # The systemd unit uses $RECEIVER_OPTIONS $DECODER_OPTIONS $NET_OPTIONS
        echo "→ Configuring readsb..."
        sudo tee /etc/default/readsb > /dev/null <<'READSB_CONF'
RECEIVER_OPTIONS="--device-type rtlsdr --gain autogain"
DECODER_OPTIONS=""
NET_OPTIONS="--net --net-api-port 8080"
READSB_CONF

        sudo systemctl enable readsb
        sudo systemctl restart readsb
        sleep 2

        if systemctl is-active --quiet readsb; then
            echo "✓ readsb is running (API on port 8080)"
        else
            echo "⚠  readsb failed to start — the RTL-SDR dongle may not be detected."
            echo "   Check: sudo journalctl -u readsb -n 20"
            echo "   You may need to reboot for the driver blacklist to take effect."
            echo ""
            read -p "   Continue FlightView setup anyway? [Y/n] " ans
            if [[ "$ans" =~ ^[Nn] ]]; then exit 1; fi
        fi
        echo ""
    fi
fi

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
if $INSTALL_KIOSK; then
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
else
    echo "→ Skipping kiosk setup (--no-kiosk)"
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
echo "╔══════════════════════════════════════════╗"
echo "║     Deployment Complete!                 ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Web UI:   http://localhost:5000         ║"
echo "║  Service:  sudo systemctl status $SERVICE_NAME  ║"
echo "║  Logs:     sudo journalctl -u $SERVICE_NAME -f  ║"
echo "║  Config:   nano $SCRIPT_DIR/.env         ║"
if $INSTALL_RTLSDR; then
echo "║                                          ║"
echo "║  readsb:   sudo systemctl status readsb  ║"
echo "║  Decoder:  http://localhost:8080/?all     ║"
fi
if $INSTALL_KIOSK; then
echo "║                                          ║"
echo "║  Reboot to start kiosk mode:             ║"
echo "║    sudo reboot                           ║"
fi
echo "╚══════════════════════════════════════════╝"
