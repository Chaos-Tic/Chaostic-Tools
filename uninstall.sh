#!/usr/bin/env bash
# ChaosticTool uninstaller — reads /var/lib/chaostictool/manifest; falls back to detection when absent
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
# Detection mode — used when no manifest is present (pre-v1.3.2 installs)
# ---------------------------------------------------------------------------
detect_and_remove() {
    echo -e "${YELLOW}[!] Running in detection mode (no manifest).${NC}"
    echo -e "    Only known ChaosticTool artefacts will be offered for removal.\n"

    # --- Launcher ---
    echo -e "\n${CYAN}[D1] Launcher${NC}"
    _rm_file /usr/local/bin/chaostictool

    # --- Source-install wrappers ---
    echo -e "\n${CYAN}[D2] Source-install wrappers${NC}"
    for name in responder whatweb xsstrike; do
        path="/usr/local/bin/$name"
        if [ -f "$path" ] && grep -q "opt/chaostictool" "$path" 2>/dev/null; then
            _rm_file "$path"
        else
            echo -e "  ${DIM}[-] not a ChaosticTool wrapper: $name${NC}"
            SKIPPED=$((SKIPPED + 1))
        fi
    done

    # --- Python-module wrappers ---
    echo -e "\n${CYAN}[D3] Python-module wrappers${NC}"
    for name in secretsdump.py psexec.py GetUserSPNs.py; do
        path="/usr/local/bin/$name"
        if [ -f "$path" ] && grep -q "impacket" "$path" 2>/dev/null; then
            _rm_file "$path"
        else
            echo -e "  ${DIM}[-] not a ChaosticTool wrapper: $name${NC}"
            SKIPPED=$((SKIPPED + 1))
        fi
    done

    # --- Direct downloads ---
    echo -e "\n${CYAN}[D4] Direct downloads${NC}"
    for f in /usr/local/bin/linpeas.sh /usr/local/bin/winpeas.exe; do
        _rm_file "$f"
    done
    if [ -f /usr/local/bin/rustscan ] && [ ! -L /usr/local/bin/rustscan ]; then
        _rm_file /usr/local/bin/rustscan
    fi

    # --- Symlinks to user-local tool dirs ---
    echo -e "\n${CYAN}[D5] Symlinks to user-local binaries${NC}"
    for p in /usr/local/bin/*; do
        [ -L "$p" ] || continue
        target="$(readlink "$p")"
        if echo "$target" | grep -qE "^/(home/[^/]+|root)/(go/bin|\.local/share/go/bin|\.cargo/bin|\.local/bin)/"; then
            _rm_file "$p"
        fi
    done

    # --- Source checkouts ---
    echo -e "\n${CYAN}[D6] Source checkouts${NC}"
    _rm_dir /opt/chaostictool
    _rm_dir /var/cache/chaostictool

    # --- Tor/proxychains ---
    echo -e "\n${CYAN}[D7] Tor/proxychains config restore${NC}"
    for bak in /etc/tor/torrc.chaostictool.bak \
               /etc/proxychains.conf.chaostictool.bak \
               /etc/proxychains4.conf.chaostictool.bak; do
        if [ -f "$bak" ]; then
            original="${bak%.chaostictool.bak}"
            cp -- "$bak" "$original"
            rm -f "$bak"
            echo -e "  ${GREEN}[+] restored:${NC} $original"
            REMOVED=$((REMOVED + 1))
        fi
    done

    # --- User-local tools ---
    echo -e "\n${CYAN}[D8] User-local tools (Go/Cargo/pipx/gem)${NC}"
    _detect_user_tools
}

_detect_user_tools() {
    local GO_BINS=(subfinder amass httpx nuclei naabu katana gau waybackurls ffuf dalfox gobuster bettercap)
    local go_found=()
    for bin in "${GO_BINS[@]}"; do
        for dir in "$ORIG_HOME/go/bin" "$ORIG_HOME/.local/share/go/bin" "/root/go/bin"; do
            [ -f "$dir/$bin" ] && go_found+=("$dir/$bin")
        done
    done
    if [ "${#go_found[@]}" -gt 0 ]; then
        echo -e "  ${YELLOW}Go binaries found:${NC}"
        for f in "${go_found[@]}"; do echo -e "    $f"; done
        if confirm "  Remove these Go binaries?"; then
            for f in "${go_found[@]}"; do rm -f "$f"; REMOVED=$((REMOVED + 1)); done
        fi
    fi

    local CARGO_BINS=(rustscan)
    local cargo_found=()
    for bin in "${CARGO_BINS[@]}"; do
        for dir in "$ORIG_HOME/.cargo/bin" "/root/.cargo/bin"; do
            [ -f "$dir/$bin" ] && cargo_found+=("$dir/$bin")
        done
    done
    if [ "${#cargo_found[@]}" -gt 0 ]; then
        echo -e "  ${YELLOW}Cargo binaries found:${NC}"
        for f in "${cargo_found[@]}"; do echo -e "    $f"; done
        if confirm "  Remove these Cargo binaries?"; then
            for f in "${cargo_found[@]}"; do rm -f "$f"; REMOVED=$((REMOVED + 1)); done
        fi
    fi

    local PIPX_NAMES=(theHarvester impacket netexec)
    if command -v pipx >/dev/null 2>&1; then
        local pipx_list
        pipx_list=$(if [ -n "$ORIG_USER" ] && [ "$ORIG_USER" != "root" ]; then
            sudo -u "$ORIG_USER" pipx list 2>/dev/null || true
        else
            pipx list 2>/dev/null || true
        fi)
        local pipx_ours=()
        for pkg in "${PIPX_NAMES[@]}"; do
            echo "$pipx_list" | grep -qi "package $pkg" && pipx_ours+=("$pkg")
        done
        if [ "${#pipx_ours[@]}" -gt 0 ]; then
            echo -e "  ${YELLOW}pipx packages:${NC}"
            for p in "${pipx_ours[@]}"; do echo -e "    $p"; done
            if confirm "  Uninstall these pipx packages?"; then
                for p in "${pipx_ours[@]}"; do
                    if [ -n "$ORIG_USER" ] && [ "$ORIG_USER" != "root" ]; then
                        sudo -u "$ORIG_USER" pipx uninstall "$p" 2>/dev/null || true
                    else
                        pipx uninstall "$p" 2>/dev/null || true
                    fi
                    REMOVED=$((REMOVED + 1))
                done
            fi
        fi
    fi

    if command -v gem >/dev/null 2>&1 && gem list wpscan 2>/dev/null | grep -q wpscan; then
        if confirm "  Uninstall wpscan via gem?"; then
            gem uninstall wpscan --executables --all 2>/dev/null || true
            REMOVED=$((REMOVED + 1))
        fi
    fi
}

# ---------------------------------------------------------------------------
# No manifest → detection fallback
# ---------------------------------------------------------------------------
if [ ! -f "$MANIFEST" ]; then
    echo -e "${YELLOW}[!] No manifest found at $MANIFEST${NC}"
    echo -e "    This installation predates the manifest system (v1.3.2+)."
    echo ""
    echo -e "  Option 1: re-run ${GREEN}sudo ./install.sh${NC} — it will generate a manifest,"
    echo -e "            then run this script again for a clean removal."
    echo -e "  Option 2: run detection mode now — scans for known ChaosticTool"
    echo -e "            artefacts and offers to remove them."
    echo ""
    if ! confirm "Run detection mode now?"; then
        echo -e "${DIM}Aborted.${NC}"
        exit 0
    fi
    detect_and_remove
    echo -e "\n${CYAN}=== Summary ===${NC}"
    echo -e "  Removed : ${GREEN}${REMOVED}${NC}"
    echo -e "  Skipped : ${DIM}${SKIPPED}${NC}"
    echo ""
    echo -e "${DIM}The project directory was not touched: ${SCRIPT_DIR}${NC}"
    echo -e "${DIM}To fully remove it: sudo rm -rf ${SCRIPT_DIR}${NC}"
    exit 0
fi

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
declare -a M_REPOS=()
declare -a M_PKGS=()

while IFS= read -r line; do
    [[ "$line" =~ ^# ]] && continue
    [[ -z "$line" ]] && continue
    case "$line" in
        file:*)        M_FILES+=("${line#file:}") ;;
        symlink:*)     M_SYMLINKS+=("${line#symlink:}") ;;
        dir:*)         M_DIRS+=("${line#dir:}") ;;
        go:*)          M_GO+=("${line#go:}") ;;
        cargo:*)       M_CARGO+=("${line#cargo:}") ;;
        pipx:*)        M_PIPX+=("${line#pipx:}") ;;
        gem:*)         M_GEM+=("${line#gem:}") ;;
        repo:*)        M_REPOS+=("${line#repo:}") ;;
        torrc:*)       M_FILES+=("/etc/tor/torrc.chaostictool.bak") ;;  # triggers restore
        proxychains:*) M_FILES+=("${line#proxychains:}.chaostictool.bak 2>/dev/null || true") ;;
        pkg:*)         M_PKGS+=("${line#pkg:}") ;;
    esac
done < "$MANIFEST"

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[1] Files installed by ChaosticTool${NC}"

APT_SOURCES_REMOVED=0

if [ "${#M_FILES[@]}" -gt 0 ]; then
    for path in "${M_FILES[@]}"; do
        _rm_file "$path"
        # Track if an apt sources list was removed (to refresh later)
        [[ "$path" == /etc/apt/sources.list.d/*.list ]] && APT_SOURCES_REMOVED=1 || true
    done
else
    echo -e "  ${DIM}No files recorded.${NC}"
fi

# Restore Tor/proxychains from backups
for bak in /etc/tor/torrc.chaostictool.bak \
           /etc/proxychains.conf.chaostictool.bak \
           /etc/proxychains4.conf.chaostictool.bak; do
    [ -f "$bak" ] || continue
    original="${bak%.chaostictool.bak}"
    cp -- "$bak" "$original"
    rm -f "$bak"
    echo -e "  ${GREEN}[+] restored:${NC} $original"
    REMOVED=$((REMOVED + 1))
done

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
        [ "$path" = "$MANIFEST_DIR" ] && continue
        _rm_dir "$path"
    done
else
    echo -e "  ${DIM}No source directories recorded.${NC}"
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[4] Extra package sources${NC}"
if [ "${#M_REPOS[@]}" -gt 0 ]; then
    for entry in "${M_REPOS[@]}"; do
        # Format: pm:conftype:path  e.g. pacman:/etc/pacman.conf:chaotic-aur
        local_pm="${entry%%:*}"
        rest="${entry#*:}"
        repo_path="${rest%%:*}"
        repo_id="${rest#*:}"
        if [ "$local_pm" = "pacman" ] && [ -f "$repo_path" ]; then
            # Remove [chaotic-aur] block from pacman.conf
            sed -i "/^\[${repo_id}\]/,/^$/d" "$repo_path" 2>/dev/null || true
            echo -e "  ${GREEN}[+] removed repo section:${NC} [${repo_id}] from $repo_path"
            REMOVED=$((REMOVED + 1))
        fi
    done
else
    echo -e "  ${DIM}No extra sources recorded.${NC}"
fi

# Refresh package index if apt sources were removed
if [ "$APT_SOURCES_REMOVED" -eq 1 ] && command -v apt >/dev/null 2>&1; then
    echo -e "  ${CYAN}[*] Refreshing apt after source removal${NC}"
    apt update -qq 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
echo -e "\n${CYAN}[5] User-local tools (Go, Cargo, pipx, gem)${NC}"

if [ "${#M_GO[@]}" -gt 0 ]; then
    echo -e "  ${YELLOW}Go binaries installed by ChaosticTool:${NC}"
    for path in "${M_GO[@]}"; do echo -e "    $path"; done
    if confirm "  Remove these Go binaries?"; then
        for path in "${M_GO[@]}"; do _rm_file "$path"; done
    else
        SKIPPED=$((SKIPPED + ${#M_GO[@]}))
    fi
else
    echo -e "  ${DIM}No Go binaries recorded.${NC}"
fi

if [ "${#M_CARGO[@]}" -gt 0 ]; then
    echo -e "  ${YELLOW}Cargo binaries installed by ChaosticTool:${NC}"
    for path in "${M_CARGO[@]}"; do echo -e "    $path"; done
    if confirm "  Remove these Cargo binaries?"; then
        for path in "${M_CARGO[@]}"; do _rm_file "$path"; done
    else
        SKIPPED=$((SKIPPED + ${#M_CARGO[@]}))
    fi
else
    echo -e "  ${DIM}No Cargo binaries recorded.${NC}"
fi

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
    echo -e "  ${DIM}These packages were installed by ChaosticTool. Remove only what you no longer need:${NC}\n"
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
