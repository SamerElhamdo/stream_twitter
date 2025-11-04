#!/bin/bash
# Installation script for Stream Server systemd service

set -e

echo "🚀 Installing Stream Server Service..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

# Get current directory
CURRENT_DIR=$(pwd)
SERVICE_USER=${SERVICE_USER:-root}
INSTALL_DIR=${INSTALL_DIR:-/root/stream_twitter}
LOG_DIR="/var/log/stream-server"
STREAM_DIR="/var/streamctl"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Installation directory: $INSTALL_DIR"
echo "  Service user: $SERVICE_USER"
echo "  Log directory: $LOG_DIR"
echo "  Stream directory: $STREAM_DIR"

# Create installation directory
echo -e "\n${YELLOW}Creating directories...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$STREAM_DIR/pids"
mkdir -p "$STREAM_DIR/logs"
mkdir -p "$INSTALL_DIR/uploads"

# Copy files
echo -e "\n${YELLOW}Copying files...${NC}"
cp -r "$CURRENT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
cp "$CURRENT_DIR"/.env "$INSTALL_DIR/" 2>/dev/null || true

# Set permissions
echo -e "\n${YELLOW}Setting permissions...${NC}"
chown -R $SERVICE_USER:$SERVICE_USER "$INSTALL_DIR"
chown -R $SERVICE_USER:$SERVICE_USER "$LOG_DIR"
chown -R $SERVICE_USER:$SERVICE_USER "$STREAM_DIR"
chmod +x "$INSTALL_DIR/main.py"

# Install Python dependencies
echo -e "\n${YELLOW}Setting up Python virtual environment...${NC}"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
"$INSTALL_DIR/venv/bin/pip" install gunicorn

# Update service file with correct paths
echo -e "\n${YELLOW}Configuring systemd service...${NC}"
sed -i "s|/opt/stream-server|$INSTALL_DIR|g" "$INSTALL_DIR/stream-server.service"
sed -i "s|www-data|$SERVICE_USER|g" "$INSTALL_DIR/stream-server.service"

# Copy service file
cp "$INSTALL_DIR/stream-server.service" /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Enable service
systemctl enable stream-server.service

echo -e "\n${GREEN}✅ Installation complete!${NC}"
echo -e "\n${YELLOW}Next steps:${NC}"
echo "  1. Edit /etc/systemd/system/stream-server.service and set:"
echo "     - WEBHOOK_TOKEN environment variable"
echo "     - Any other environment variables needed"
echo ""
echo "  2. Start the service:"
echo "     ${GREEN}sudo systemctl start stream-server${NC}"
echo ""
echo "  3. Check status:"
echo "     ${GREEN}sudo systemctl status stream-server${NC}"
echo ""
echo "  4. View logs:"
echo "     ${GREEN}sudo journalctl -u stream-server -f${NC}"
echo ""
