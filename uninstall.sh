#!/usr/bin/env bash
# ChaosticTool uninstaller — reads /var/lib/chaostictool/manifest to remove only what install.sh installed
set -Eeuo pipefail

GREEN='\033[1;32m'; RED='\033[1;31m'; CYAN='\033[1;36m'; YELLOW='\033[1;33m'; DIM='\033[2m'; NC='\033[0m'
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

MANIFEST_DIR="/var/lib/chaostictool"
MANIFEST="$MANIFEST_DIR/manifest"

echo -e "${CYAN}=== ChaosticTool uninstaller ===${NC}\n"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[!] This script requires root privileges.${NC}"
    echo -e "    Re-run with: ${GREEN}sudo ./uninstall.sh${NC}\n"
    exit 1
fi

if [ ! -f "$MANIFEST" ]; then
    echo -e "${YELLOW}[!] No manifest found at $MANIFEST${NC}"
    echo -e "    Either ChaosticTool was never installed via install.sh, or it was installed"
    echo -e "    before the manifest system was introduced (v1.3.2+)."
    echo -e "    Nothing to remove.\n"
    exit 0
fi

ORIG_USER="${SUDO_USER:-}"
ORIG_HOME=""
if [ -n "$ORIG_USER" ] && [ "$ORIG_USER" != "root" ]; then
    ORIG_HOME="$(getent passwd "$ORIG_USER" 2>/dev/null | cut -d: -f6 || true)"
fi
[ -z "$ORIG_HOME" ] && ORIG_HOME="/root"

confirm() {
    local prompt="$1"
    echo -en "${YELLOW}${prompt} [y/N]${NC} "
    read -r rep
    case "${rep,,}" in
        y|yes|o|oui) return 0 ;;
        *) return 1 ;;
    esac
}

REMOVED=0
SKIPPED=0

_rm_file() {
    local path="$1"
    if [ -e "$path" ] || [ -L "$path" ]; then
        rm -f "$path"
        echo -e "  ${GREEN}[+] removed:${NC} $path"
        REMOVED=$((REMOVED + 1))
    else
        echo -e "  ${DIM}[-] not found: $path${NC}"
        SKIPPED=$((SKIPPED + 1))
    fi
}

_rm_dir() {
    local path="$1"
    if [ -d "$path" ]; then
        rm -rf "$path"
        echo -e "  ${GREEN}[+] removed dir:${NC} $path"
        REMOVED=$((REMOVED + 1))
    else
        echo -e "  ${DIM}[-] not found: $path${NC}"
        SKIPPED=$((SKIPPED + 1))
    fi
}

# ---------------------------------------------------------------------------
# Parse manifest into typed arrays
# ---------------------------------------------------------------------------
declare -a M_FILES=()
declare -a M_SYMLINKS=()
declare -a M_DIRS=()
declare -a M_GO=()
declare -a M_CARGO=()
declare -a M_PIPX=()
declare -a M_GEM=()
declare -a M_TORRC=()
declare -a M_PROXYCHAINS=()
# pkg entries: "pm:pkgname" — collected for display only (never auto-removed)
declare -a M_PKGS=()

while IFS= read -r line; do
    [[ "$line" =~ ^# ]] && continue
    [[ -z "$line" ]] && continue
    case "$line" in
        file:*)       M_FILES+=("${line#file:}") ;;
        symlink:*)    M_SYMLINKS+=("${line#symlink:}") ;;
        dir:*)        M_DIRS+=("${line#dir:}") ;;
        go:*)         M_GO+=("${line#go:}") ;;
        cargo:*)      M_CARGO+=("${line#cargo:}") ;;
        pipx:*)       M_PIPX+=("${line#pipx:}") ;;
        gem:*)        M_GEM+=("${line#gem:}") ;;
        torrc:*)      M_TORRC+=("${line#torrc:}") ;;
        proxychains:*)M_PROXYCHAINS+=("${line#proxychains:}") ;;
        pkg:*)        M_PKGS+=("${line#pkg:}") ;;
    esac
done < "$MANIFEST"

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[1] Files installed by ChaosticTool${NC}"
if [ "${#M_FILES[@]}" -gt 0 ]; then
    for path in "${M_FILES[@]}"; do
        _rm_file "$path"
    done
else
    echo -e "  ${DIM}No files recorded.${NC}"
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[2] Symlinks to user-local binaries${NC}"
if [ "${#M_SYMLINKS[@]}" -gt 0 ]; then
    for path in "${M_SYMLINKS[@]}"; do
        _rm_file "$path"
    done
else
    echo -e "  ${DIM}No symlinks recorded.${NC}"
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[3] Source checkouts and staging directories${NC}"
if [ "${#M_DIRS[@]}" -gt 0 ]; then
    for path in "${M_DIRS[@]}"; do
        # Never auto-remove the manifest dir itself — handled last
        [ "$path" = "$MANIFEST_DIR" ] && continue
        _rm_dir "$path"
    done
else
    echo -e "  ${DIM}No source directories recorded.${NC}"
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[4] Restoring Tor and proxychains configurations${NC}"
_restore_bak() {
    local bak="$1"
    if [ -f "$bak" ]; then
        local original="${bak%.chaostictool.bak}"
        cp -- "$bak" "$original"
        rm -f "$bak"
        echo -e "  ${GREEN}[+] restored:${NC} $original"
        REMOVED=$((REMOVED + 1))
    else
        echo -e "  ${DIM}[-] no backup: $bak${NC}"
        SKIPPED=$((SKIPPED + 1))
    fi
}
for bak in /etc/tor/torrc.chaostictool.bak \
           /etc/proxychains.conf.chaostictool.bak \
           /etc/proxychains4.conf.chaostictool.bak; do
    _restore_bak "$bak"
done

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[5] User-local tools (Go, Cargo, pipx, gem)${NC}"

# --- Go binaries ---
if [ "${#M_GO[@]}" -gt 0 ]; then
    echo -e "  ${YELLOW}Go binaries installed by ChaosticTool:${NC}"
    for path in "${M_GO[@]}"; do echo -e "    $path"; done
    if confirm "  Remove these Go binaries?"; then
        for path in "${M_GO[@]}"; do
            _rm_file "$path"
        done
    else
        SKIPPED=$((SKIPPED + ${#M_GO[@]}))
    fi
else
    echo -e "  ${DIM}No Go binaries recorded.${NC}"
fi

# --- Cargo binaries ---
if [ "${#M_CARGO[@]}" -gt 0 ]; then
    echo -e "  ${YELLOW}Cargo binaries installed by ChaosticTool:${NC}"
    for path in "${M_CARGO[@]}"; do echo -e "    $path"; done
    if confirm "  Remove these Cargo binaries?"; then
        for path in "${M_CARGO[@]}"; do
            _rm_file "$path"
        done
    else
        SKIPPED=$((SKIPPED + ${#M_CARGO[@]}))
    fi
else
    echo -e "  ${DIM}No Cargo binaries recorded.${NC}"
fi

# --- pipx packages ---
if [ "${#M_PIPX[@]}" -gt 0 ]; then
    echo -e "  ${YELLOW}pipx packages installed by ChaosticTool:${NC}"
    for pkg in "${M_PIPX[@]}"; do echo -e "    $pkg"; done
    if confirm "  Uninstall these pipx packages?"; then
        for pkg in "${M_PIPX[@]}"; do
            if [ -n "$ORIG_USER" ] && [ "$ORIG_USER" != "root" ] && command -v pipx >/dev/null 2>&1; then
                sudo -u "$ORIG_USER" pipx uninstall "$pkg" 2>/dev/null || true
            elif command -v pipx >/dev/null 2>&1; then
                pipx uninstall "$pkg" 2>/dev/null || true
            fi
            echo -e "  ${GREEN}[+] pipx uninstalled:${NC} $pkg"
            REMOVED=$((REMOVED + 1))
        done
    else
        SKIPPED=$((SKIPPED + ${#M_PIPX[@]}))
    fi
else
    echo -e "  ${DIM}No pipx packages recorded.${NC}"
fi

# --- gem packages ---
if [ "${#M_GEM[@]}" -gt 0 ]; then
    echo -e "  ${YELLOW}gem packages installed by ChaosticTool:${NC}"
    for pkg in "${M_GEM[@]}"; do echo -e "    $pkg"; done
    if confirm "  Uninstall these gem packages?"; then
        for pkg in "${M_GEM[@]}"; do
            if command -v gem >/dev/null 2>&1; then
                gem uninstall "$pkg" --executables --all 2>/dev/null || true
                echo -e "  ${GREEN}[+] gem uninstalled:${NC} $pkg"
                REMOVED=$((REMOVED + 1))
            fi
        done
    else
        SKIPPED=$((SKIPPED + ${#M_GEM[@]}))
    fi
else
    echo -e "  ${DIM}No gem packages recorded.${NC}"
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[6] System packages — review manually${NC}"
if [ "${#M_PKGS[@]}" -gt 0 ]; then
    echo -e "  ${DIM}These packages were installed by ChaosticTool. They are NOT removed${NC}"
    echo -e "  ${DIM}automatically — remove only what you no longer need:${NC}\n"
    declare -A by_pm=()
    for entry in "${M_PKGS[@]}"; do
        pm="${entry%%:*}"
        pkg="${entry#*:}"
        by_pm["$pm"]+=" $pkg"
    done
    for pm in "${!by_pm[@]}"; do
        pkgs="${by_pm[$pm]}"
        case "$pm" in
            pacman) echo -e "  ${DIM}sudo pacman -Rs${pkgs}${NC}" ;;
            apt)    echo -e "  ${DIM}sudo apt remove --autoremove${pkgs}${NC}" ;;
            dnf)    echo -e "  ${DIM}sudo dnf remove${pkgs}${NC}" ;;
            *)      echo -e "  ${DIM}${pm} remove${pkgs}${NC}" ;;
        esac
    done
else
    echo -e "  ${DIM}No system packages recorded.${NC}"
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[7] Manifest directory${NC}"
_rm_dir "$MANIFEST_DIR"

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}=== Summary ===${NC}"
echo -e "  Removed : ${GREEN}${REMOVED}${NC}"
echo -e "  Skipped : ${DIM}${SKIPPED}${NC}"
echo ""
echo -e "${DIM}The project directory was not touched: ${SCRIPT_DIR}${NC}"
echo -e "${DIM}To fully remove it: sudo rm -rf ${SCRIPT_DIR}${NC}"
