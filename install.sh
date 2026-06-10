#!/usr/bin/env bash
# ChaosticTool installer
# Default: fast bootstrap plus official distro packages. Heavy builds/source installs are opt-in.
set -Eeuo pipefail

GREEN='\033[1;32m'; RED='\033[1;31m'; CYAN='\033[1;36m'; YELLOW='\033[1;33m'; DIM='\033[2m'; NC='\033[0m'
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PROFILE="standard"
WITH_TOR=0
ASSUME_YES=0
NO_TOOLS=0
REFRESH_DONE=0

MANIFEST_DIR="/var/lib/chaostictool"
MANIFEST="$MANIFEST_DIR/manifest"

usage() {
    cat <<EOF
ChaosticTool installer

Usage:
  sudo ./install.sh [options]

Options:
  --profile minimal      Install only Python runtime and ChaosticTool launcher.
  --profile standard     Install fast, official distro packages only. Default.
  --profile full         Also install Go/Cargo/pipx/pip/gem/source/AUR tools and Tor routing. Installs language
                         toolchains (Go, Rust, Ruby) and clones some tools into /opt/chaostictool/. Can be slow.
                         Tor is started for the current session only — not enabled at boot.
  --with-tor             Install and configure Tor/proxychains support for minimal/standard profiles.
  --no-tools             Skip external pentest tools.
  -y, --yes              Accepted for compatibility; installs are non-interactive.
  -h, --help             Show this help.

Examples:
  sudo ./install.sh
  sudo ./install.sh --profile minimal
  sudo ./install.sh --with-tor
  sudo ./install.sh --profile full
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --profile)
            if [ "$#" -lt 2 ]; then
                echo -e "${RED}[!] Missing value for --profile.${NC}"
                usage
                exit 1
            fi
            shift
            PROFILE="$1"
            ;;
        --profile=*)
            PROFILE="${1#*=}"
            ;;
        --minimal)
            PROFILE="minimal"
            ;;
        --standard)
            PROFILE="standard"
            ;;
        --full)
            PROFILE="full"
            ;;
        --with-tor)
            WITH_TOR=1
            ;;
        --no-tools)
            NO_TOOLS=1
            ;;
        -y|--yes)
            ASSUME_YES=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}[!] Unknown option: $1${NC}"
            usage
            exit 1
            ;;
    esac
    shift
done

case "$PROFILE" in
    minimal|standard|full) ;;
    *)
        echo -e "${RED}[!] Invalid profile: $PROFILE${NC}"
        usage
        exit 1
        ;;
esac

echo -e "${CYAN}=== ChaosticTool installer ===${NC}\n"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[!] This script requires root privileges.${NC}"
    echo -e "    Re-run with: ${GREEN}sudo ./install.sh${NC}\n"
    exit 1
fi

detect_pm() {
    if command -v pacman >/dev/null 2>&1; then
        echo "pacman"
    elif command -v apt >/dev/null 2>&1; then
        echo "apt"
    elif command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v zypper >/dev/null 2>&1; then
        echo "zypper"
    elif command -v apk >/dev/null 2>&1; then
        echo "apk"
    else
        echo ""
    fi
}

PM="$(detect_pm)"
ORIG_USER="${SUDO_USER:-}"

echo -e "Profile         : ${GREEN}${PROFILE}${NC}"
echo -e "Package manager : ${GREEN}${PM:-none}${NC}"
if [ "$WITH_TOR" -eq 1 ] || [ "$PROFILE" = "full" ]; then
    echo -e "Tor setup       : ${GREEN}enabled${NC}"
else
    echo -e "Tor setup       : ${DIM}skipped${NC}"
fi
[ -n "$ORIG_USER" ] && echo -e "Sudo user       : ${GREEN}${ORIG_USER}${NC}"
echo ""

manifest_init() {
    mkdir -p "$MANIFEST_DIR"
    printf '# ChaosticTool manifest\n# date=%s profile=%s pm=%s\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PROFILE" "${PM:-none}" >> "$MANIFEST"
    manifest_record "dir:${MANIFEST_DIR}"
    export CHAOSTICTOOL_MANIFEST="$MANIFEST"
}

manifest_record() {
    printf '%s\n' "$1" >> "$MANIFEST"
}

confirm() {
    local prompt="$1"
    if [ "$ASSUME_YES" -eq 1 ]; then
        return 0
    fi
    echo -en "${YELLOW}${prompt} [y/N]${NC} "
    read -r rep
    case "${rep,,}" in
        y|yes|o|oui) return 0 ;;
        *) return 1 ;;
    esac
}

pm_refresh() {
    [ -n "$PM" ] || return 0
    [ "$REFRESH_DONE" -eq 0 ] || return 0
    case "$PM" in
        apt)
            echo -e "${CYAN}[*] Refreshing apt metadata${NC}"
            apt update
            ;;
        zypper)
            echo -e "${CYAN}[*] Refreshing zypper metadata${NC}"
            zypper --non-interactive refresh
            ;;
        apk)
            echo -e "${CYAN}[*] Refreshing apk metadata${NC}"
            apk update
            ;;
        dnf)
            echo -e "${CYAN}[*] Refreshing dnf metadata${NC}"
            dnf makecache -y
            ;;
    esac
    REFRESH_DONE=1
}

pm_recover_metadata() {
    case "$PM" in
        pacman)
            echo -e "${CYAN}[*] Refreshing pacman package databases after install failure${NC}"
            pacman -Syy --noconfirm
            ;;
        apt)
            echo -e "${CYAN}[*] Refreshing apt metadata after install failure${NC}"
            apt update
            ;;
        dnf)
            echo -e "${CYAN}[*] Refreshing dnf metadata after install failure${NC}"
            dnf makecache -y
            ;;
        *)
            return 1
            ;;
    esac
}

pkg_installed() {
    local pkg="$1"
    case "$PM" in
        pacman) pacman -Q "$pkg" >/dev/null 2>&1 ;;
        apt) dpkg -s "$pkg" >/dev/null 2>&1 ;;
        dnf|zypper) rpm -q "$pkg" >/dev/null 2>&1 ;;
        apk) apk info -e "$pkg" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}

pkg_available() {
    local pkg="$1"
    case "$PM" in
        pacman) pacman -Si "$pkg" >/dev/null 2>&1 ;;
        apt) apt-cache show "$pkg" >/dev/null 2>&1 ;;
        dnf) dnf -q list --available "$pkg" >/dev/null 2>&1 || dnf -q list installed "$pkg" >/dev/null 2>&1 ;;
        zypper)
            zypper --non-interactive search --match-exact --type package "$pkg" 2>/dev/null \
                | awk -F'|' -v p="$pkg" 'NR > 2 {gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($2 == p) found=1} END {exit found ? 0 : 1}'
            ;;
        apk) apk search -x "$pkg" 2>/dev/null | grep -q . ;;
        *) return 1 ;;
    esac
}

pm_install() {
    case "$PM" in
        pacman) pacman -S --noconfirm --needed -- "$@" ;;
        apt) DEBIAN_FRONTEND=noninteractive apt install -y --no-install-recommends "$@" ;;
        dnf) dnf install -y "$@" ;;
        zypper) zypper --non-interactive install --no-recommends "$@" ;;
        apk) apk add --no-cache "$@" ;;
        *) return 1 ;;
    esac
}

install_packages() {
    local label="$1"
    shift
    [ "$#" -gt 0 ] || return 0

    if [ -z "$PM" ]; then
        echo -e "${YELLOW}[!] No supported package manager found. Skipping $label packages.${NC}"
        return 1
    fi

    pm_refresh || true

    local wanted=()
    local pkg
    for pkg in "$@"; do
        if pkg_installed "$pkg"; then
            echo -e "  ${DIM}already installed: $pkg${NC}"
        elif pkg_available "$pkg"; then
            wanted+=("$pkg")
        else
            echo -e "  ${YELLOW}unavailable in enabled repos: $pkg${NC}"
        fi
    done

    [ "${#wanted[@]}" -gt 0 ] || return 0

    echo -e "\n${CYAN}[*] Installing $label packages:${NC} ${wanted[*]}"
    if ! pm_install "${wanted[@]}"; then
        if [ "$PM" = "pacman" ]; then
            pm_recover_metadata || true
            echo -e "${YELLOW}[!] Retrying $label packages individually after pacman metadata refresh.${NC}"
            local failed=0
            for pkg in "${wanted[@]}"; do
                if ! pm_install "$pkg"; then
                    failed=1
                else
                    manifest_record "pkg:${PM}:${pkg}"
                fi
            done
            if [ "$failed" -eq 0 ]; then
                return 0
            fi
            echo -e "${YELLOW}[!] pacman still failed after refreshing databases.${NC}"
            echo -e "${DIM}    Your Arch mirrorlist may be stale or temporarily out of sync.${NC}"
            echo -e "${DIM}    Refresh mirrors, run: sudo pacman -Syyu, then retry ChaosticTool.${NC}"
        fi
        echo -e "${YELLOW}[!] Some $label packages failed to install. Continuing with verification.${NC}"
        return 1
    fi
    for pkg in "${wanted[@]}"; do
        manifest_record "pkg:${PM}:${pkg}"
    done
}

pip_install_requirements() {
    if ! command -v python3 >/dev/null 2>&1; then
        return 1
    fi
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo -e "${RED}[!] pip is unavailable and Rich could not be installed.${NC}"
        return 1
    fi
    python3 -m pip install --break-system-packages -r "$SCRIPT_DIR/requirements.txt" \
        || python3 -m pip install -r "$SCRIPT_DIR/requirements.txt"
}

install_python_runtime() {
    local packages=()
    case "$PM" in
        pacman) packages=(python python-pip python-rich curl ca-certificates) ;;
        apt) packages=(python3 python3-pip python3-rich curl ca-certificates) ;;
        dnf) packages=(python3 python3-pip python3-rich curl ca-certificates) ;;
        zypper) packages=(python3 python3-pip python3-rich curl ca-certificates) ;;
        apk) packages=(python3 py3-pip py3-rich curl ca-certificates) ;;
    esac

    install_packages "runtime" "${packages[@]}" || true

    if ! command -v python3 >/dev/null 2>&1; then
        echo -e "${RED}[!] python3 is still missing.${NC}"
        echo -e "${YELLOW}Install Python 3 manually, then re-run this script.${NC}"
        exit 1
    fi

    if ! python3 -c "import rich" >/dev/null 2>&1; then
        echo -e "${CYAN}[*] Installing Python dependency with pip fallback: rich${NC}"
        pip_install_requirements || {
            echo -e "${RED}[!] Python dependency install failed: rich is still unavailable.${NC}"
            exit 1
        }
    fi

    echo -e "${GREEN}[+] $(python3 --version 2>&1)${NC}"
    echo -e "${GREEN}[+] Python dependencies OK${NC}\n"
}

standard_packages() {
    case "$PM" in
        pacman)
            printf '%s\n' whois bind nmap masscan gobuster wafw00f whatweb nikto testssl.sh sslscan sqlmap python-impacket hashcat john hydra aircrack-ng tcpdump curl
            ;;
        apt)
            printf '%s\n' whois dnsutils nmap masscan gobuster wafw00f whatweb nikto sslscan sqlmap python3-impacket hashcat john hydra aircrack-ng tcpdump curl
            ;;
        dnf)
            printf '%s\n' whois bind-utils nmap masscan nikto sslscan sqlmap hashcat john hydra aircrack-ng tcpdump curl
            ;;
        zypper)
            printf '%s\n' whois bind-utils nmap masscan hashcat john hydra aircrack-ng tcpdump curl
            ;;
        apk)
            printf '%s\n' whois bind-tools nmap masscan hydra aircrack-ng tcpdump curl
            ;;
    esac
}

tor_packages() {
    case "$PM" in
        pacman) printf '%s\n' tor proxychains-ng curl ;;
        apt) printf '%s\n' tor proxychains4 curl ;;
        dnf) printf '%s\n' tor proxychains-ng curl ;;
        zypper) printf '%s\n' tor proxychains-ng curl ;;
        apk) printf '%s\n' tor proxychains-ng curl ;;
    esac
}

setup_epel() {
    [ "$PM" = "dnf" ] || return 0
    [ -f /etc/redhat-release ] || return 0
    grep -qiE "centos|rhel|red hat enterprise|almalinux|rocky" /etc/redhat-release || return 0
    if rpm -q epel-release >/dev/null 2>&1; then
        echo -e "  ${DIM}EPEL already enabled${NC}"
        return 0
    fi
    echo -e "${YELLOW}[!] EPEL not enabled — many security tools require it on RHEL/CentOS${NC}"
    if confirm "Enable EPEL now? (recommended)"; then
        if dnf install -y epel-release; then
            manifest_record "pkg:dnf:epel-release"
        fi
        REFRESH_DONE=0
        pm_refresh || true
    fi
}

install_standard_tools() {
    local packages=()
    while IFS= read -r pkg; do
        [ -n "$pkg" ] && packages+=("$pkg")
    done < <(standard_packages)

    install_packages "standard tool" "${packages[@]}" || true
}

configure_torrc() {
    local torrc="/etc/tor/torrc"
    local tor_user=""

    if getent passwd tor >/dev/null 2>&1; then
        tor_user="tor"
    elif getent passwd debian-tor >/dev/null 2>&1; then
        tor_user="debian-tor"
    fi

    echo -e "${CYAN}[*] Configuring Tor service${NC}"
    install -d -m 0755 /etc/tor
    touch "$torrc"
    install -d -m 0700 /var/lib/tor || true
    if [ -n "$tor_user" ]; then
        chown -R "${tor_user}:${tor_user}" /var/lib/tor 2>/dev/null || chown -R "$tor_user" /var/lib/tor 2>/dev/null || true
    fi

    TOR_USER="$tor_user" python3 - "$torrc" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
tor_user = os.environ.get("TOR_USER", "").strip()
required = {"SocksPort": "9050", "DataDirectory": "/var/lib/tor"}
if tor_user:
    required["User"] = tor_user

original = path.read_text(encoding="utf-8", errors="surrogateescape") if path.exists() else ""
backup = path.with_name(path.name + ".chaostictool.bak")
if original and not backup.exists():
    backup.write_text(original, encoding="utf-8", errors="surrogateescape")

seen = set()
out = []
by_lower = {k.lower(): (k, v) for k, v in required.items()}
for line in original.splitlines(keepends=True):
    stripped = line.strip()
    key = stripped.split(None, 1)[0].lower() if stripped and not stripped.startswith("#") else ""
    if key in by_lower:
        directive, value = by_lower[key]
        if key not in seen:
            out.append(f"{directive} {value}\n")
            seen.add(key)
        else:
            out.append("# ChaosticTool disabled duplicate: " + line)
    else:
        out.append(line)

if out and not "".join(out).endswith("\n"):
    out.append("\n")
for key, value in required.items():
    if key.lower() not in seen:
        out.append(f"{key} {value}\n")
path.write_text("".join(out), encoding="utf-8", errors="surrogateescape")
PY
}

configure_proxychains() {
    local configs=()
    [ -f /etc/proxychains.conf ] && configs+=("/etc/proxychains.conf")
    [ -f /etc/proxychains4.conf ] && configs+=("/etc/proxychains4.conf")

    if [ "${#configs[@]}" -eq 0 ]; then
        configs=("/etc/proxychains.conf")
        cat > /etc/proxychains.conf <<'EOF'
dynamic_chain
proxy_dns
tcp_read_time_out 15000
tcp_connect_time_out 8000

[ProxyList]
socks5 127.0.0.1 9050
EOF
    fi

    python3 - "${configs[@]}" <<'PY'
from pathlib import Path
import sys

for raw in sys.argv[1:]:
    path = Path(raw)
    text = path.read_text(encoding="utf-8", errors="surrogateescape") if path.exists() else ""
    backup = path.with_name(path.name + ".chaostictool.bak")
    if text and not backup.exists():
        backup.write_text(text, encoding="utf-8", errors="surrogateescape")

    lines = text.splitlines()
    active = [line.strip().lower() for line in lines if line.strip() and not line.strip().startswith("#")]
    out = []
    for line in lines:
        token = line.strip().split(None, 1)[0].lower() if line.strip() else ""
        if token in {"strict_chain", "random_chain", "round_robin_chain"} and not line.lstrip().startswith("#"):
            out.append("#" + line)
        else:
            out.append(line)

    text = "\n".join(out).rstrip() + "\n" if out else ""
    if "dynamic_chain" not in active:
        text = "dynamic_chain\n" + text
    if "proxy_dns" not in active:
        text = "proxy_dns\n" + text
    if "[proxylist]" not in active:
        text += "\n[ProxyList]\n"
    if not any(line.startswith("socks5 127.0.0.1 9050") or line.startswith("socks5 localhost 9050") for line in active):
        text += "socks5 127.0.0.1 9050\n"
    path.write_text(text, encoding="utf-8", errors="surrogateescape")
PY
}

wait_for_tor_socks() {
    python3 - <<'PY'
import socket
import sys
import time

deadline = time.time() + 12
while time.time() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 9050), timeout=1):
            sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit(1)
PY
}

start_tor_service() {
    if ! command -v tor >/dev/null 2>&1; then
        echo -e "${YELLOW}[!] tor binary is missing; skipping service start.${NC}"
        return 1
    fi

    echo -e "${CYAN}[*] Starting Tor service${NC}"
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files tor.service >/dev/null 2>&1; then
        systemctl reset-failed tor >/dev/null 2>&1 || true
        systemctl start tor || true
    elif command -v service >/dev/null 2>&1; then
        service tor start || true
    else
        echo -e "${YELLOW}[!] No supported service manager found. Start Tor manually when needed.${NC}"
    fi

    if wait_for_tor_socks; then
        echo -e "${GREEN}[+] Tor SOCKS listener ready on 127.0.0.1:9050${NC}"
        return 0
    fi

    echo -e "${YELLOW}[!] Tor did not expose 127.0.0.1:9050 yet. Check the Tor service status.${NC}"
    return 1
}

setup_tor() {
    if [ "$WITH_TOR" -ne 1 ] && [ "$PROFILE" != "full" ]; then
        return 0
    fi

    local packages=()
    while IFS= read -r pkg; do
        [ -n "$pkg" ] && packages+=("$pkg")
    done < <(tor_packages)

    install_packages "Tor routing" "${packages[@]}" || true
    echo -e "${DIM}[*] /etc/tor/torrc and /etc/proxychains*.conf will be updated. Originals backed up as *.chaostictool.bak${NC}"
    configure_torrc || true
    manifest_record "torrc:/etc/tor/torrc"
    configure_proxychains || true
    for _conf in /etc/proxychains.conf /etc/proxychains4.conf; do
        [ -f "$_conf" ] && manifest_record "proxychains:${_conf}"
    done
    start_tor_service || true
    echo ""
}

install_extended_tools() {
    [ "$NO_TOOLS" -eq 1 ] && return 0
    [ "$PROFILE" = "minimal" ] && return 0

    echo -e "\n${CYAN}[*] Installing cross-platform tools${NC}"
    if [ "$PROFILE" = "standard" ]; then
        python3 - <<'PY'
from core.installer import install_missing
from core.tools import TOOLS
from core.ui import SUPPORT_TOOLS, tool_available
registry = {**TOOLS, **SUPPORT_TOOLS}
missing = [(key, tool["binary"]) for key, tool in registry.items() if not tool_available(tool)]
install_missing(missing, assume_yes=True, allowed_methods={"go", "pipx", "pip", "gem", "pywrap", "release", "direct"})
PY
    else
        python3 - <<'PY'
from core.installer import install_missing
from core.tools import TOOLS
from core.ui import SUPPORT_TOOLS, tool_available
registry = {**TOOLS, **SUPPORT_TOOLS}
missing = [(key, tool["binary"]) for key, tool in registry.items() if not tool_available(tool)]
install_missing(missing, assume_yes=True)
PY
    fi
}

install_launcher() {
    local tmp
    tmp="$(mktemp)"
    {
        printf '#!/usr/bin/env bash\n'
        printf 'cd %q\n' "$SCRIPT_DIR"
        printf 'exec python3 %q "$@"\n' "$SCRIPT_DIR/chaostictool.py"
    } > "$tmp"
    install -m 0755 "$tmp" /usr/local/bin/chaostictool
    rm -f "$tmp"
    chmod +x "$SCRIPT_DIR/chaostictool.py" "$SCRIPT_DIR/install.sh"
    manifest_record "file:/usr/local/bin/chaostictool"
    echo -e "${GREEN}[+] Launcher installed: /usr/local/bin/chaostictool${NC}"
}

link_registered_user_bins() {
    python3 - <<'PY'
from pathlib import Path
import os

try:
    from core.tools import TOOLS
    from core.ui import SUPPORT_TOOLS
except Exception:
    TOOLS = {}
    SUPPORT_TOOLS = {}

names = set()
for tool in {**TOOLS, **SUPPORT_TOOLS}.values():
    names.add(tool.get("binary", ""))
    names.update(tool.get("binary_alternatives", []))
names.discard("")

homes = []
sudo_user = os.environ.get("SUDO_USER", "")
if sudo_user:
    homes.append(Path("/home") / sudo_user)
homes.append(Path("/root"))

dirs = []
for home in homes:
    dirs.extend([
        home / "go" / "bin",
        home / ".local" / "share" / "go" / "bin",
        home / ".cargo" / "bin",
        home / ".local" / "bin",
    ])

manifest_path = os.environ.get("CHAOSTICTOOL_MANIFEST", "")
linked = 0
Path("/usr/local/bin").mkdir(parents=True, exist_ok=True)
for name in sorted(names):
    dst = Path("/usr/local/bin") / name
    if dst.is_symlink() and not dst.exists():
        dst.unlink()
    if dst.exists():
        continue
    for directory in dirs:
        src = directory / name
        if src.is_file() and os.access(src, os.X_OK):
            try:
                dst.symlink_to(src)
                linked += 1
                if manifest_path:
                    with open(manifest_path, "a", encoding="utf-8") as _mf:
                        _mf.write(f"symlink:{dst}\n")
            except OSError:
                pass
            break

print(f"[+] Linked user-installed registered tools: {linked}")
PY
}

show_tool_report() {
    echo -e "\n${CYAN}=== Tool availability report ===${NC}"
    python3 - <<'PY'
from core.tools import TOOLS
from core.ui import SUPPORT_TOOLS, tool_available

registry = {**TOOLS, **SUPPORT_TOOLS}
present = []
missing = []
for key, tool in registry.items():
    (present if tool_available(tool) else missing).append(tool["binary"])

print(f"Ready: {len(present)} | Missing: {len(missing)}")
if missing:
    print("Missing: " + ", ".join(missing))
PY
}

install_python_runtime
manifest_init
setup_epel

if [ "$NO_TOOLS" -eq 0 ]; then
    case "$PROFILE" in
        minimal)
            echo -e "${DIM}[*] Minimal profile: external tools skipped.${NC}"
            ;;
        standard|full)
            install_standard_tools
            ;;
    esac
else
    echo -e "${DIM}[*] --no-tools selected: external tools skipped.${NC}"
fi

setup_tor
install_extended_tools
install_launcher
link_registered_user_bins
show_tool_report

echo ""
echo -e "${GREEN}Launch:${NC} sudo chaostictool"
echo -e "${DIM}If not found: sudo /usr/local/bin/chaostictool${NC}"
echo -e "${DIM}Or from this directory: sudo python3 chaostictool.py${NC}"
echo -e "${DIM}Tip: use 'sudo ./install.sh --profile full' later for the heavy optional arsenal (AUR, source builds).${NC}"
