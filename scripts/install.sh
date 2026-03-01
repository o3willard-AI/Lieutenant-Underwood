#!/bin/bash
#
# Lieutenant-Underwood (LM Studio TUI) Installation Script
# One-line install: curl -sSL https://install.lmstui.dev | sudo bash
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/lieutenant-underwood"
BIN_DIR="/usr/local/bin"
USER_CONFIG_DIR="$HOME/.config/lmstui"
REPO_URL="https://github.com/o3willard-AI/Lieutenant-Underwood"
MIN_PYTHON_VERSION="3.10"

# Helper functions
print_error() {
    echo -e "${RED}✗ $1${NC}" >&2
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

check_sudo() {
    if [ "$EUID" -ne 0 ]; then 
        print_error "This script must be run with sudo"
        echo "Please run: curl -sSL https://install.lmstui.dev | sudo bash"
        exit 1
    fi
}

check_python() {
    print_info "Checking Python version..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        echo "Please install Python 3.10 or higher:"
        echo "  sudo apt update && sudo apt install python3 python3-pip"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    
    if [ "$(printf '%s\n' "$MIN_PYTHON_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$MIN_PYTHON_VERSION" ]; then
        print_error "Python $PYTHON_VERSION is installed, but $MIN_PYTHON_VERSION or higher is required"
        exit 1
    fi
    
    print_success "Python $PYTHON_VERSION found"
}

check_os() {
    print_info "Checking operating system..."
    
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" != "ubuntu" && "$ID_LIKE" != *"ubuntu"* && "$ID" != "debian" && "$ID_LIKE" != *"debian"* ]]; then
            print_warning "This installer is designed for Ubuntu/Debian"
            echo "Detected: $NAME"
            read -p "Continue anyway? [y/N] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_warning "Cannot detect OS. Proceeding anyway..."
    fi
}

download_and_install() {
    print_info "Downloading Lieutenant-Underwood..."
    
    # Create temp directory
    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"
    
    # Download latest release
    print_info "Fetching latest release from GitHub..."
    LATEST_URL=$(curl -s https://api.github.com/repos/o3willard-AI/Lieutenant-Underwood/releases/latest | grep "tarball_url" | cut -d '"' -f 4)
    
    if [ -z "$LATEST_URL" ]; then
        # Fallback to cloning master
        print_info "Downloading from master branch..."
        git clone --depth 1 "$REPO_URL" ltu
        cd ltu
    else
        curl -sL "$LATEST_URL" -o ltu.tar.gz
        tar -xzf ltu.tar.gz --strip-components=1
    fi
    
    print_success "Download complete"
}

install_app() {
    print_info "Installing to $INSTALL_DIR..."
    
    # Remove old installation if exists
    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Removing existing installation..."
        rm -rf "$INSTALL_DIR"
    fi
    
    # Create installation directory
    mkdir -p "$INSTALL_DIR"
    
    # Copy application files
    cp -r src "$INSTALL_DIR/"
    cp pyproject.toml "$INSTALL_DIR/"
    cp README.md "$INSTALL_DIR/"
    cp CHANGELOG.md "$INSTALL_DIR/"
    
    # Create __init__.py for launcher module
    touch "$INSTALL_DIR/src/lmstudio_tui/__init__.py"
    
    print_success "Application installed"
}

create_launcher() {
    print_info "Creating launcher..."
    
    cat > "$BIN_DIR/lmstui" << 'EOF'
#!/bin/bash
# Lieutenant-Underwood Launcher
# Installed: /opt/lieutenant-underwood

PYTHONPATH="/opt/lieutenant-underwood/src:$PYTHONPATH" \
    python3 -m lmstudio_tui.launcher "$@"
EOF
    
    chmod +x "$BIN_DIR/lmstui"
    
    print_success "Launcher created at $BIN_DIR/lmstui"
}

setup_user_config() {
    print_info "Setting up user configuration..."
    
    # Get the actual user (not root)
    REAL_USER=${SUDO_USER:-$USER}
    REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
    
    USER_CONFIG="$REAL_HOME/.config/lmstui"
    
    mkdir -p "$USER_CONFIG"
    
    # Create default config if not exists
    if [ ! -f "$USER_CONFIG/config.toml" ]; then
        cat > "$USER_CONFIG/config.toml" << EOF
# Lieutenant-Underwood Configuration
# Auto-generated on $(date)

[lmstudio]
# Host and port for LM Studio API
# Auto-detected at runtime if not specified
# host = "localhost"
# port = 1234

[ui]
# UI refresh rate in seconds
refresh_rate = 1.0

[logging]
# Log level: DEBUG, INFO, WARNING, ERROR
level = "INFO"
EOF
        chown -R "$REAL_USER:$(id -gn "$REAL_USER")" "$USER_CONFIG"
        print_success "Default config created at $USER_CONFIG/config.toml"
    else
        print_info "User config already exists, preserving"
    fi
}

create_uninstaller() {
    print_info "Creating uninstaller..."
    
    cat > "$INSTALL_DIR/uninstall.sh" << 'EOF'
#!/bin/bash
# Lieutenant-Underwood Uninstaller

set -e

INSTALL_DIR="/opt/lieutenant-underwood"
BIN_DIR="/usr/local/bin"

echo "Uninstalling Lieutenant-Underwood..."

# Remove installation directory
if [ -d "$INSTALL_DIR" ]; then
    echo "Removing $INSTALL_DIR..."
    rm -rf "$INSTALL_DIR"
fi

# Remove launcher
if [ -L "$BIN_DIR/lmstui" ] || [ -f "$BIN_DIR/lmstui" ]; then
    echo "Removing $BIN_DIR/lmstui..."
    rm -f "$BIN_DIR/lmstui"
fi

echo "✓ Lieutenant-Underwood uninstalled successfully"
echo ""
echo "User config at ~/.config/lmstui/ was preserved."
echo "To remove it manually: rm -rf ~/.config/lmstui/"
EOF
    
    chmod +x "$INSTALL_DIR/uninstall.sh"
    
    print_success "Uninstaller created at $INSTALL_DIR/uninstall.sh"
}

print_banner() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}        Lieutenant-Underwood Installer v0.2.0         ${BLUE}║${NC}"
    echo -e "${BLUE}║${NC}           LM Studio Terminal User Interface            ${BLUE}║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_completion() {
    echo ""
    print_success "Installation complete!"
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}  Launch: ${YELLOW}lmstui${NC}                                     ${GREEN}║${NC}"
    echo -e "${GREEN}║${NC}  Docs:   ${YELLOW}https://github.com/o3willard-AI/Lieutenant-Underwood${NC} ${GREEN}║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Uninstall anytime with: sudo /opt/lieutenant-underwood/uninstall.sh"
    echo ""
}

# Main installation flow
main() {
    print_banner
    
    check_sudo
    check_os
    check_python
    
    print_info "Starting installation..."
    
    # Download
    download_and_install
    
    # Install
    install_app
    create_launcher
    setup_user_config
    create_uninstaller
    
    # Cleanup
    cd /
    rm -rf "$TEMP_DIR"
    
    print_completion
}

# Handle uninstall argument
if [ "$1" == "--uninstall" ]; then
    if [ -f "$INSTALL_DIR/uninstall.sh" ]; then
        exec "$INSTALL_DIR/uninstall.sh"
    else
        print_error "Lieutenant-Underwood is not installed"
        exit 1
    fi
fi

# Run main installation
main
