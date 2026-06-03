#!/bin/bash
#
# Lieutenant-Underwood (LM Studio TUI) — Install / Upgrade / Uninstall Script
#
# Usage:
#   Fresh install:  sudo bash install.sh
#   Upgrade:        sudo bash install.sh --upgrade
#   Uninstall:      sudo bash install.sh --uninstall
#
# Requirements: Python 3.9+, git, curl
#

set -e

# ── Configuration ────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/lieutenant-underwood"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="/usr/local/bin"
REPO_URL="https://github.com/o3willard-AI/Lieutenant-Underwood"
MIN_PYTHON_VERSION="3.9"
LTU_VERSION=""  # set from pyproject.toml after source is downloaded

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_error()   { echo -e "${RED}✗ $1${NC}" >&2; }
print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }

print_banner() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  Lieutenant-Underwood Installer                        ${BLUE}║${NC}"
    echo -e "${BLUE}║${NC}  LM Studio Terminal User Interface                    ${BLUE}║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# ── Pre-flight checks ────────────────────────────────────────────────────────
check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run with sudo"
        echo "Usage: sudo bash install.sh [--upgrade|--uninstall]"
        exit 1
    fi
}

check_python() {
    print_info "Checking Python version..."

    if ! command -v python3 &>/dev/null; then
        print_error "Python 3 is not installed"
        echo "  sudo apt update && sudo apt install python3 python3-venv python3-pip"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')

    if [ "$(printf '%s\n' "$MIN_PYTHON_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$MIN_PYTHON_VERSION" ]; then
        print_error "Python $PYTHON_VERSION found but $MIN_PYTHON_VERSION+ is required"
        exit 1
    fi

    # Ensure python3-venv is available
    if ! python3 -m venv --help &>/dev/null; then
        print_error "python3-venv not found"
        echo "  sudo apt install python3-venv"
        exit 1
    fi

    print_success "Python $PYTHON_VERSION OK"
}

# ── Download ─────────────────────────────────────────────────────────────────
download_source() {
    print_info "Downloading Lieutenant-Underwood from GitHub..."

    TEMP_DIR=$(mktemp -d)
    trap 'rm -rf "$TEMP_DIR"' EXIT

    # Always pull the master branch archive — this is what gets pushed to,
    # not GitHub Releases (which would pin to the last tagged version).
    ARCHIVE_URL="https://github.com/o3willard-AI/Lieutenant-Underwood/archive/refs/heads/master.tar.gz"
    if ! curl -fsSL "$ARCHIVE_URL" -o "$TEMP_DIR/ltu.tar.gz"; then
        print_error "Failed to download source from GitHub"
        exit 1
    fi
    mkdir -p "$TEMP_DIR/ltu"
    tar -xzf "$TEMP_DIR/ltu.tar.gz" -C "$TEMP_DIR/ltu" --strip-components=1
    SOURCE_DIR="$TEMP_DIR/ltu"

    LTU_VERSION=$(grep '^version' "$SOURCE_DIR/pyproject.toml" | head -1 | cut -d '"' -f 2)
    print_success "Download complete (v${LTU_VERSION})"
}

# ── Install steps ─────────────────────────────────────────────────────────────
copy_app_files() {
    mkdir -p "$INSTALL_DIR"
    cp -r "$SOURCE_DIR/src" "$INSTALL_DIR/"
    cp "$SOURCE_DIR/pyproject.toml" "$INSTALL_DIR/"
    [ -f "$SOURCE_DIR/README.md" ]    && cp "$SOURCE_DIR/README.md"    "$INSTALL_DIR/"
    [ -f "$SOURCE_DIR/CHANGELOG.md" ] && cp "$SOURCE_DIR/CHANGELOG.md" "$INSTALL_DIR/"
    print_success "Application files installed to $INSTALL_DIR"
}

create_venv() {
    print_info "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    print_success "Virtual environment created at $VENV_DIR"
}

install_python_deps() {
    print_info "Installing Python dependencies..."
    "$VENV_DIR/bin/pip" install "$INSTALL_DIR" -q
    print_success "Python dependencies installed"
}

grant_net_raw() {
    # The HTTP sniffer runs tcpdump as a subprocess; tcpdump needs CAP_NET_RAW.
    # setcap lives in /usr/sbin on Debian/Ubuntu which may not be in PATH
    # even under sudo depending on sudoers secure_path setting.
    TCPDUMP_BIN=$(command -v tcpdump 2>/dev/null \
        || { ls /usr/bin/tcpdump /usr/sbin/tcpdump 2>/dev/null | head -1; })
    SETCAP_BIN=$(command -v setcap 2>/dev/null || echo /usr/sbin/setcap)

    if [ -z "$TCPDUMP_BIN" ] || [ ! -x "$TCPDUMP_BIN" ]; then
        print_warning "tcpdump not found — network sniffer disabled (install: apt install tcpdump)"
        return
    fi

    if [ -x "$SETCAP_BIN" ]; then
        "$SETCAP_BIN" cap_net_raw+eip "$TCPDUMP_BIN" && \
            print_success "cap_net_raw granted to $TCPDUMP_BIN (network sniffer enabled)" || \
            print_warning "setcap failed — run manually: sudo setcap cap_net_raw+eip $TCPDUMP_BIN"
    else
        print_warning "setcap not found (install libcap2-bin) — run manually: sudo setcap cap_net_raw+eip $TCPDUMP_BIN"
    fi
}

verify_installation() {
    print_info "Verifying installation..."
    if "$VENV_DIR/bin/python" -c "import lmstudio_tui" 2>/dev/null; then
        VERSION=$("$VENV_DIR/bin/python" -c "from lmstudio_tui import __version__; print(__version__)")
        print_success "Installed version: $VERSION"
    else
        print_error "Verification failed — lmstudio_tui not importable"
        print_info "Check: $VENV_DIR/bin/pip install $INSTALL_DIR"
        exit 1
    fi
}

create_launcher() {
    print_info "Creating launcher at $BIN_DIR/lmstui..."
    cat > "$BIN_DIR/lmstui" << EOF
#!/bin/bash
exec "$VENV_DIR/bin/python" -m lmstudio_tui.launcher "\$@"
EOF
    chmod +x "$BIN_DIR/lmstui"
    print_success "Launcher created"
}

setup_user_config() {
    REAL_USER="${SUDO_USER:-$USER}"
    REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
    CONFIG_DIR="$REAL_HOME/.config/lmstudio-tui"

    if [ ! -f "$CONFIG_DIR/config.toml" ]; then
        mkdir -p "$CONFIG_DIR"
        cat > "$CONFIG_DIR/config.toml" << TOML
# Lieutenant-Underwood Configuration
# Generated $(date)

[server]
host = "localhost"
port = 1234

[gpu]
update_frequency = 2.0

[chat]
system_prompt = "You are a helpful assistant."
TOML
        chown -R "$REAL_USER:$(id -gn "$REAL_USER")" "$CONFIG_DIR"
        print_success "Default config created at $CONFIG_DIR/config.toml"
    else
        print_info "Existing config preserved at $CONFIG_DIR/config.toml"
    fi
}

create_uninstaller() {
    cat > "$INSTALL_DIR/uninstall.sh" << 'UNINSTALL'
#!/bin/bash
# Lieutenant-Underwood Uninstaller

set -e

INSTALL_DIR="/opt/lieutenant-underwood"
BIN_DIR="/usr/local/bin"

if [ "$EUID" -ne 0 ]; then
    echo "Please run with sudo: sudo bash /opt/lieutenant-underwood/uninstall.sh"
    exit 1
fi

echo "Uninstalling Lieutenant-Underwood..."

# Stop any running instance
pkill -f "lmstudio_tui.launcher" 2>/dev/null && echo "Stopped running instance" || true

# Remove pip package from venv
if [ -f "$INSTALL_DIR/venv/bin/pip" ]; then
    "$INSTALL_DIR/venv/bin/pip" uninstall -y lmstudio-tui 2>/dev/null || true
fi

# Remove install directory
[ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR" && echo "Removed $INSTALL_DIR"

# Remove launcher
[ -f "$BIN_DIR/lmstui" ] && rm -f "$BIN_DIR/lmstui" && echo "Removed $BIN_DIR/lmstui"

echo ""
echo "✓ Lieutenant-Underwood uninstalled successfully"
echo ""
echo "User config at ~/.config/lmstudio-tui/ was preserved."
echo "To remove it: rm -rf ~/.config/lmstudio-tui/"
UNINSTALL

    chmod +x "$INSTALL_DIR/uninstall.sh"
    print_success "Uninstaller created at $INSTALL_DIR/uninstall.sh"
}

print_completion() {
    echo ""
    print_success "Installation complete!"
    echo ""
    echo -e "${GREEN}  Launch:     ${YELLOW}lmstui${NC}"
    echo -e "${GREEN}  Upgrade:    ${YELLOW}sudo bash install.sh --upgrade${NC}"
    echo -e "${GREEN}  Uninstall:  ${YELLOW}sudo /opt/lieutenant-underwood/uninstall.sh${NC}"
    echo -e "${GREEN}  Docs:       ${YELLOW}$REPO_URL${NC}"
    echo ""
}

# ── Upgrade ──────────────────────────────────────────────────────────────────
do_upgrade() {
    print_banner
    check_sudo
    check_python

    if [ ! -d "$INSTALL_DIR" ]; then
        print_error "Lieutenant-Underwood is not installed. Run without --upgrade."
        exit 1
    fi

    print_info "Stopping any running instance..."
    pkill -f "lmstudio_tui.launcher" 2>/dev/null || true

    download_source

    print_info "Updating application files..."
    rm -rf "$INSTALL_DIR/src"
    cp -r "$SOURCE_DIR/src" "$INSTALL_DIR/"
    cp "$SOURCE_DIR/pyproject.toml" "$INSTALL_DIR/"
    [ -f "$SOURCE_DIR/README.md" ]    && cp "$SOURCE_DIR/README.md"    "$INSTALL_DIR/"
    [ -f "$SOURCE_DIR/CHANGELOG.md" ] && cp "$SOURCE_DIR/CHANGELOG.md" "$INSTALL_DIR/"

    print_info "Updating Python dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade "$INSTALL_DIR" -q
    grant_net_raw

    verify_installation
    create_launcher   # Recreate launcher in case venv path changed

    echo ""
    print_success "Upgrade complete! Run: lmstui"
    echo ""
}

# ── Uninstall ─────────────────────────────────────────────────────────────────
do_uninstall() {
    check_sudo
    if [ -f "$INSTALL_DIR/uninstall.sh" ]; then
        exec bash "$INSTALL_DIR/uninstall.sh"
    else
        # Uninstaller script not present — do it inline
        print_warning "Uninstaller script not found — removing manually..."
        pkill -f "lmstudio_tui.launcher" 2>/dev/null || true
        [ -d "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
        [ -f "$BIN_DIR/lmstui" ] && rm -f "$BIN_DIR/lmstui"
        print_success "Uninstalled"
    fi
}

# ── Main fresh install ────────────────────────────────────────────────────────
do_install() {
    print_banner
    check_sudo
    check_python

    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Existing installation found at $INSTALL_DIR"
        read -p "Remove and reinstall? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Tip: use --upgrade to update in place."
            exit 0
        fi
        pkill -f "lmstudio_tui.launcher" 2>/dev/null || true
        rm -rf "$INSTALL_DIR"
    fi

    download_source
    copy_app_files
    create_venv
    install_python_deps
    grant_net_raw
    verify_installation
    create_launcher
    setup_user_config
    create_uninstaller

    print_completion
}

# ── Entry point ───────────────────────────────────────────────────────────────
case "${1:-}" in
    --upgrade)   do_upgrade ;;
    --uninstall) do_uninstall ;;
    "")          do_install ;;
    *)
        echo "Usage: sudo bash install.sh [--upgrade|--uninstall]"
        exit 1
        ;;
esac
