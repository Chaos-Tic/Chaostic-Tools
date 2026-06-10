import io
import json
import os
import platform
import pwd
import re
import shlex
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
import zipfile
from contextlib import suppress

from rich.console import Console
from rich.table import Table
from rich.theme import Theme

THEME = Theme(
    {
        "brand.red": "bold #ff3131",
        "brand.warn": "bold #ffb84d",
        "brand.ok": "bold #31ff83",
        "brand.info": "bold #67e8f9",
        "brand.muted": "#a98c91",
        "brand.command": "#ffb4b4",
        "brand.white": "bold #f8fafc",
    }
)

console = Console(theme=THEME)


def _manifest_record(entry: str) -> None:
    path = os.environ.get("CHAOSTICTOOL_MANIFEST", "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except OSError:
        pass


# Maps pipx install target → canonical package name used by `pipx uninstall`
_PIPX_CANONICAL: dict[str, str] = {
    "git+https://github.com/laramies/theHarvester.git": "theHarvester",
    "impacket": "impacket",
    "git+https://github.com/Pennyw0rth/NetExec": "netexec",
}


def _get_original_user():
    """Returns (username, pw_entry) of the user who ran sudo, or None."""
    user = os.environ.get("SUDO_USER", "")
    if user and user != "root":
        try:
            return user, pwd.getpwnam(user)
        except KeyError:
            pass
    return None, None


def _drop_privs(pw):
    """preexec_fn: drops root to become the pw user again before exec."""
    def fn():
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.environ["HOME"] = pw.pw_dir
        os.environ["USER"] = pw.pw_name
        os.environ["LOGNAME"] = pw.pw_name
    return fn


def _run(cmd, as_user_pw=None, env=None):
    """Runs cmd, optionally dropping root to as_user_pw."""
    console.print(f"[brand.command]  $ {shlex.join(cmd)}[/brand.command]")
    try:
        kwargs = {}
        if as_user_pw is not None:
            kwargs["preexec_fn"] = _drop_privs(as_user_pw)
        if env is not None:
            kwargs["env"] = env
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0:
            console.print(f"[bright_red][!] Command finished with code {result.returncode}[/bright_red]")
            return False
        return True
    except FileNotFoundError:
        console.print(f"[bright_red][!] Command not found: {cmd[0]}[/bright_red]")
        return False
    except PermissionError as e:
        console.print(f"[bright_red][!] Permission denied: {e}[/bright_red]")
        return False

# ---- Per-tool installation table ----
# Each entry: (method, package_or_module)
# methods: "pkg"    = system package manager (pacman/apt/dnf automatic)
#          "aur"    = direct AUR build on Arch
#          "go"     = go install (cross-platform)
#          "cargo"  = cargo install (cross-platform)
#          "pywrap" = wrapper around an already installed Python module
#          "release"= release archive download
#          "pipx"   = isolated Python CLI install
#          "pip"    = pip3 install (cross-platform)
#          "gem"    = RubyGems install
#          "source" = source checkout + local wrapper
#          "direct" = release asset download
#
# Cross-platform philosophy:
#   - official distro packages are preferred when present in enabled repos
#   - Go-based tools fall back to "go install" before AUR source builds
#   - Arch-only gaps use direct AUR builds without requiring yay/paru
#   - portable PEASS assets are downloaded directly into /usr/local/bin

# Package names per manager for "pkg" tools
PKG_NAMES = {
    #  binary            pacman                   apt                      dnf
    "whois":           ("whois",                  "whois",                  "whois"),
    "dig":             ("bind",                   "dnsutils",               "bind-utils"),
    "subfinder":       (None,                     None,                     None),
    "dnsrecon":        (None,                     "dnsrecon",               None),
    "shodan":          ("python-shodan",          None,                     None),
    "nmap":            ("nmap",                   "nmap",                   "nmap"),
    "rustscan":        ("rustscan",               None,                     None),
    "masscan":         ("masscan",                "masscan",                "masscan"),
    "gobuster":        ("gobuster",               "gobuster",               None),
    "httpx":           (None,                     None,                     None),
    "wafw00f":         ("wafw00f",                "wafw00f",                None),
    "whatweb":         (None,                     "whatweb",                None),
    "nikto":           ("nikto",                  "nikto",                  "nikto"),
    "nuclei":          (None,                     None,                     None),
    "wpscan":          ("wpscan",                 None,                     None),
    "testssl":         ("testssl.sh",             "testssl.sh",             None),
    "testssl.sh":      ("testssl.sh",             "testssl.sh",             None),
    "sslscan":         ("sslscan",                "sslscan",                "sslscan"),
    "sqlmap":          ("sqlmap",                 "sqlmap",                 "sqlmap"),
    "msfconsole":      ("metasploit",             "metasploit-framework",   None),
    "msfvenom":        ("metasploit",             "metasploit-framework",   None),
    "secretsdump.py":  ("python-impacket",        "python3-impacket",       None),
    "psexec.py":       ("python-impacket",        "python3-impacket",       None),
    "GetUserSPNs.py":  ("python-impacket",        "python3-impacket",       None),
    "hashcat":         ("hashcat",                "hashcat",                "hashcat"),
    "john":            ("john",                   "john",                   "john"),
    "hydra":           ("hydra",                  "hydra",                  "hydra"),
    "airmon-ng":       ("aircrack-ng",            "aircrack-ng",            "aircrack-ng"),
    "airodump-ng":     ("aircrack-ng",            "aircrack-ng",            "aircrack-ng"),
    "aircrack-ng":     ("aircrack-ng",            "aircrack-ng",            "aircrack-ng"),
    "reaver":          ("reaver",                 "reaver",                 None),
    "wifite":          ("wifite",                 "wifite",                 None),
    "bettercap":       ("bettercap",              None,                     None),
    "ettercap":        ("ettercap",               "ettercap-graphical",     "ettercap"),
    "tcpdump":         ("tcpdump",                "tcpdump",                "tcpdump"),
    "responder":       (None,                     "responder",              None),
    "nxc":             (None,                     "netexec",                None),
    "proxychains4":    ("proxychains-ng",         "proxychains4",           "proxychains-ng"),
    "tor":             ("tor",                    "tor",                    "tor"),
    "curl":            ("curl",                   "curl",                   "curl"),
}
_PM_INDEX = {"pacman": 0, "apt": 1, "dnf": 2}

# Tools installable via go install (cross-platform)
GO_MODULES = {
    "amass":            "github.com/owasp-amass/amass/v4/...@master",
    "subfinder":        "github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest",
    "httpx":            "github.com/projectdiscovery/httpx/cmd/httpx@latest",
    "nuclei":           "github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest",
    "naabu":            "github.com/projectdiscovery/naabu/v2/cmd/naabu@latest",
    "katana":           "github.com/projectdiscovery/katana/cmd/katana@latest",
    "gau":              "github.com/lc/gau/v2/cmd/gau@latest",
    "waybackurls":      "github.com/tomnomnom/waybackurls@latest",
    "ffuf":             "github.com/ffuf/ffuf/v2@latest",
    "dalfox":           "github.com/hahwul/dalfox/v2@latest",
    "gobuster":         "github.com/OJ/gobuster/v3@latest",
    "bettercap":        "github.com/bettercap/bettercap/v2@latest",
    "rustscan":         None,   # Rust, not Go — cargo install rustscan
}

# Tools installable via cargo (cross-platform when Rust is available)
CARGO_PACKAGES = {
    "rustscan": "rustscan",
}

# Tools installable via RubyGems when no distro package is available.
GEM_PACKAGES = {
    "wpscan": "wpscan",
}

# Python CLI tools installed in isolated user environments.
PIPX_PACKAGES = {
    "theHarvester": "git+https://github.com/laramies/theHarvester.git",
    "secretsdump.py": "impacket",
    "psexec.py": "impacket",
    "GetUserSPNs.py": "impacket",
    "nxc": "git+https://github.com/Pennyw0rth/NetExec",
}

# Tools installable via pip (cross-platform)
PIP_PACKAGES = {
    "dnsrecon":          "dnsrecon",
    "shodan":            "shodan",
    "xsstrike":          "xsstrike",
    "bloodhound-python": "bloodhound",
    "crackmapexec":      "crackmapexec",
    "nxc":               None,
    "wpscan":            None,   # gem, not pip
}

DIRECT_DOWNLOADS = {
    "linpeas.sh": {
        "url": "https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh",
        "path": "/usr/local/bin/linpeas.sh",
        "mode": 0o755,
    },
    "winpeas.exe": {
        "url": "https://github.com/peass-ng/PEASS-ng/releases/latest/download/winPEASx64.exe",
        "path": "/usr/local/bin/winpeas.exe",
        "mode": 0o755,
    },
}

RELEASE_ASSETS = {
    "rustscan": {
        "api_url": "https://api.github.com/repos/RustScan/RustScan/releases/latest",
        "binary": "rustscan",
        "path": "/usr/local/bin/rustscan",
        "assets": {
            "aarch64": ["aarch64-linux-rustscan.zip"],
            "arm64": ["aarch64-linux-rustscan.zip"],
            "x86_64": ["x86_64-linux-rustscan.tar.gz.zip", "rustscan.deb.zip"],
            "amd64": ["x86_64-linux-rustscan.tar.gz.zip", "rustscan.deb.zip"],
        },
    },
}

SOURCE_INSTALLS = {
    "responder": {
        "repo": "https://github.com/lgandx/Responder.git",
        "path": "/opt/chaostictool/Responder",
        "entry": "Responder.py",
        "runner": "python3",
        "wrapper": "/usr/local/bin/responder",
    },
    "whatweb": {
        "repo": "https://github.com/urbanadventurer/WhatWeb.git",
        "path": "/opt/chaostictool/WhatWeb",
        "entry": "whatweb",
        "runner": "ruby",
        "wrapper": "/usr/local/bin/whatweb",
    },
    "xsstrike": {
        "repo": "https://github.com/s0md3v/XSStrike.git",
        "path": "/opt/chaostictool/XSStrike",
        "entry": "xsstrike.py",
        "runner": "python3",
        "requirements": "requirements.txt",
        "wrapper": "/usr/local/bin/xsstrike",
    },
}

PYTHON_MODULE_WRAPPERS = {
    "secretsdump.py": {
        "module": "impacket.examples.secretsdump",
        "wrapper": "/usr/local/bin/secretsdump.py",
    },
    "psexec.py": {
        "module": "impacket.examples.psexec",
        "wrapper": "/usr/local/bin/psexec.py",
    },
    "GetUserSPNs.py": {
        "module": "impacket.examples.GetUserSPNs",
        "wrapper": "/usr/local/bin/GetUserSPNs.py",
    },
}

BUILD_DEPS = {
    "rustscan": {
        "pacman": ["rust", "base-devel", "pkgconf", "openssl"],
        "apt": ["cargo", "rustc", "build-essential", "pkg-config", "libssl-dev"],
        "dnf": ["cargo", "rust", "gcc", "make", "pkgconf-pkg-config", "openssl-devel"],
    },
    "bettercap": {
        "pacman": ["base-devel", "libpcap", "libusb", "libnetfilter_queue"],
        "apt": [
            "git",
            "golang",
            "build-essential",
            "pkg-config",
            "libpcap-dev",
            "libusb-1.0-0-dev",
            "libnetfilter-queue-dev",
        ],
        "dnf": [
            "git",
            "golang",
            "gcc",
            "make",
            "pkgconf-pkg-config",
            "libpcap-devel",
            "libusb1-devel",
            "libnetfilter_queue-devel",
        ],
    },
    "wpscan": {
        "pacman": ["ruby", "base-devel"],
        "apt": [
            "ruby-full",
            "build-essential",
            "libcurl4-openssl-dev",
            "libxml2-dev",
            "libxslt1-dev",
            "zlib1g-dev",
        ],
        "dnf": [
            "ruby",
            "ruby-devel",
            "gcc",
            "make",
            "libcurl-devel",
            "libxml2-devel",
            "libxslt-devel",
            "zlib-devel",
        ],
    },
    "nxc": {
        "pacman": ["python-pipx", "python-virtualenv", "rust", "base-devel", "git"],
        "apt": ["pipx", "python3-venv", "python3-dev", "build-essential", "rustc", "cargo", "git"],
        "dnf": ["pipx", "python3-devel", "gcc", "make", "rust", "cargo", "git"],
    },
    "secretsdump.py": {
        "pacman": ["python-pipx", "python-virtualenv"],
        "apt": ["pipx", "python3-venv"],
        "dnf": ["pipx", "python3-virtualenv"],
    },
    "psexec.py": {
        "pacman": ["python-pipx", "python-virtualenv"],
        "apt": ["pipx", "python3-venv"],
        "dnf": ["pipx", "python3-virtualenv"],
    },
    "GetUserSPNs.py": {
        "pacman": ["python-pipx", "python-virtualenv"],
        "apt": ["pipx", "python3-venv"],
        "dnf": ["pipx", "python3-virtualenv"],
    },
    "theHarvester": {
        "pacman": ["python-pipx", "python-virtualenv", "git"],
        "apt": ["pipx", "python3-venv", "git"],
        "dnf": ["pipx", "python3-virtualenv", "git"],
    },
    "xsstrike": {
        "pacman": ["git", "python", "python-pip"],
        "apt": ["git", "python3", "python3-pip"],
        "dnf": ["git", "python3", "python3-pip"],
    },
    "whatweb": {
        "pacman": ["git", "ruby"],
        "apt": ["git", "ruby"],
        "dnf": ["git", "ruby"],
    },
    "responder": {
        "pacman": ["git", "python", "python-netifaces"],
        "apt": ["git", "python3", "python3-netifaces"],
        "dnf": ["git", "python3", "python3-netifaces"],
    },
}

AUR_PACKAGES = {
    "subfinder": "subfinder",
    "theHarvester": "theharvester-git",
    "whatweb": "whatweb",
    "nuclei": "nuclei",
    "naabu": "naabu",
    "xsstrike": "xsstrike",
    "responder": "responder",
    "ffuf": "ffuf",
    "dalfox": "dalfox",
    "waybackurls": "waybackurls-bin",
    "bloodhound-python": "python-bloodhound",
    "crackmapexec": "netexec",
    "nxc": "netexec",
}


_AUR_USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# Root-owned staging area — never chowned to the build user
_AUR_STAGING = "/var/cache/chaostictool/aur"


_DEP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _parse_srcinfo_deps(srcinfo_path):
    """Return (depends, makedepends) parsed from .SRCINFO — strips version constraints.
    Each name is validated against _DEP_RE; entries that fail are silently dropped."""
    deps, makedeps = [], []
    try:
        for line in open(srcinfo_path):
            line = line.strip()
            for prefix, bucket in (("depends =", deps), ("makedepends =", makedeps)):
                if line.startswith(prefix):
                    name = re.split(r"[>=<]", line.split("=", 1)[1].strip())[0]
                    if _DEP_RE.match(name):
                        bucket.append(name)
    except OSError:
        pass
    return deps, makedeps


def _ensure_aur_build_prereqs(pm):
    if pm != "pacman":
        return True

    console.print("\n[brand.info][*] Installing AUR build prerequisites[/brand.info]")
    _run(["pacman", "-S", "--needed", "--noconfirm", "pacman", "git", "base-devel"])

    missing = [binary for binary in ("git", "makepkg") if not shutil.which(binary)]
    if not missing:
        return True

    console.print(
        f"[brand.red][!] AUR build prerequisites still missing: {', '.join(missing)}[/brand.red]"
    )
    if "makepkg" in missing:
        console.print("[brand.muted]    On Arch, makepkg is provided by the pacman package.[/brand.muted]")
    console.print("[brand.muted]    Install manually: sudo pacman -S --needed pacman git base-devel[/brand.muted]")
    return False


def _install_aur_direct(pkg_names, orig_user, orig_pw):
    """
    Build AUR packages as orig_user, install as root — no sudoers entry needed.

    Flow per package:
      1. git clone into a root-owned staging dir
      2. parse .SRCINFO → install all deps as root via pacman (no user sudo needed)
      3. chown only the source subdir to orig_user so makepkg can write
      4. makepkg --nodeps (deps already present) as orig_user
      5. cp built .pkg.tar.* back to the root-owned staging dir
      6. pacman -U from the root-owned copy
      7. clean up staging dir
    """
    import glob
    import shutil as _shutil
    if not _AUR_USER_RE.match(orig_user):
        console.print(f"[brand.red][!] Unexpected username format: {orig_user!r} — AUR install aborted.[/brand.red]")
        return

    for binary in ("git", "makepkg"):
        if not shutil.which(binary):
            console.print(f"[brand.warn][!] {binary} is required for AUR installs — skipping.[/brand.warn]")
            return

    os.makedirs(_AUR_STAGING, mode=0o700, exist_ok=True)

    for pkg_name in pkg_names:
        aur_url = f"https://aur.archlinux.org/{pkg_name}.git"
        console.print(f"\n[brand.info][*] AUR: {pkg_name}[/brand.info]")

        stage = os.path.join(_AUR_STAGING, pkg_name)
        src_dir = os.path.join(stage, "src")
        out_dir = os.path.join(stage, "out")
        try:
            _shutil.rmtree(stage, ignore_errors=True)
            os.makedirs(src_dir, mode=0o700)
            os.makedirs(out_dir, mode=0o700)

            # Clone into root-owned src_dir
            r = subprocess.run(
                ["git", "clone", "--depth=1", aur_url, src_dir],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                console.print(f"[brand.red][!] git clone failed: {r.stderr.strip()}[/brand.red]")
                continue

            # Install all deps as root — makepkg will run with --nodeps
            deps, makedeps = _parse_srcinfo_deps(os.path.join(src_dir, ".SRCINFO"))
            all_deps = list(dict.fromkeys(deps + makedeps))  # dedup, preserve order
            if all_deps:
                console.print(f"[brand.info][*] Installing deps: {' '.join(all_deps)}[/brand.info]")
                subprocess.run(
                    ["pacman", "-S", "--asdeps", "--needed", "--noconfirm", "--"] + all_deps,
                    check=False,
                )

            # Chown only src_dir so makepkg can write (out_dir stays root-owned)
            subprocess.run(["chown", "-R", f"{orig_user}:{orig_user}", src_dir], check=False)

            env = dict(os.environ)
            env["HOME"] = orig_pw.pw_dir
            env["USER"] = orig_user
            env["LOGNAME"] = orig_user
            # Direct makepkg output to the user-owned src_dir (default behaviour)
            # --nodeps: deps already installed above; no sudo needed inside makepkg
            r = subprocess.run(
                ["makepkg", "--nodeps", "--noconfirm"],
                cwd=src_dir,
                preexec_fn=_drop_privs(orig_pw),
                env=env,
            )
            if r.returncode != 0:
                console.print(f"[brand.red][!] makepkg failed for {pkg_name}[/brand.red]")
                continue

            # Copy artifacts to root-owned out_dir before calling pacman
            built_src = [
                p for p in glob.glob(os.path.join(src_dir, "*.pkg.tar.*"))
                if not p.endswith(".sig")
            ]
            if not built_src:
                console.print(f"[brand.red][!] No package file produced for {pkg_name}[/brand.red]")
                continue

            built_dst = []
            for src in built_src:
                dst = os.path.join(out_dir, os.path.basename(src))
                _shutil.copy2(src, dst)
                os.chown(dst, 0, 0)
                os.chmod(dst, 0o644)
                built_dst.append(dst)

            r = subprocess.run(["pacman", "-U", "--noconfirm", "--needed"] + built_dst)
            if r.returncode == 0:
                _manifest_record(f"pkg:pacman:{pkg_name}")
                console.print(f"[brand.ok][+] {pkg_name} installed[/brand.ok]")
            else:
                console.print(f"[brand.red][!] pacman -U failed for {pkg_name}[/brand.red]")

        finally:
            _shutil.rmtree(stage, ignore_errors=True)


def _binary_exists(binary):
    """Like shutil.which() but also checks ~/go/bin and SUDO_USER paths."""
    if shutil.which(binary):
        return True
    sudo_user = os.environ.get("SUDO_USER", "")
    extra = [
        f"/home/{sudo_user}/go/bin",
        f"/home/{sudo_user}/.local/share/go/bin",
        f"/home/{sudo_user}/.cargo/bin",
        f"/home/{sudo_user}/.local/bin",
    ] if sudo_user else []
    extra += [
        os.path.expanduser("~/go/bin"),
        os.path.expanduser("~/.local/share/go/bin"),
        os.path.expanduser("~/.cargo/bin"),
        os.path.expanduser("~/.local/bin"),
    ]
    return any(os.path.isfile(os.path.join(d, binary)) for d in extra)


def _tool_available(key, binary):
    try:
        from core.tools import TOOLS
        from core.ui import SUPPORT_TOOLS, tool_available

        tool = {**TOOLS, **SUPPORT_TOOLS}.get(key)
        if tool:
            return tool_available(tool)
    except Exception:
        pass
    return _binary_exists(binary)


def _detect_pkg_manager():
    """Returns (pm, aur_helper). aur_helper is kept for compatibility; AUR builds are direct."""
    if shutil.which("pacman"):
        aur = next((h for h in ("paru", "yay") if shutil.which(h)), None)
        return "pacman", aur
    if shutil.which("apt"):
        return "apt", None
    if shutil.which("dnf"):
        return "dnf", None
    return None, None


def _package_installed(pm, pkg):
    checks = {
        "pacman": ["pacman", "-Q", pkg],
        "apt": ["dpkg", "-s", pkg],
        "dnf": ["rpm", "-q", pkg],
    }
    cmd = checks.get(pm)
    if not cmd:
        return False
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def _package_available(pm, pkg):
    checks = {
        "pacman": ["pacman", "-Si", pkg],
        "apt": ["apt-cache", "show", pkg],
        "dnf": ["dnf", "-q", "list", "--available", pkg],
    }
    cmd = checks.get(pm)
    if not cmd:
        return True
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def _refresh_package_metadata(pm):
    if pm == "apt":
        _run(["apt", "update"])


def _recover_package_metadata(pm):
    if pm == "pacman":
        console.print(
            "\n[brand.info][*] Refreshing pacman package databases after install failure[/brand.info]"
        )
        return _run(["pacman", "-Syy", "--noconfirm"])
    if pm == "apt":
        return _run(["apt", "update"])
    if pm == "dnf":
        return _run(["dnf", "makecache", "-y"])
    return False


def _filter_installable_packages(pm, pkgs):
    """Keep installable packages and skip missing repo entries without failing the batch."""
    kept = []
    for pkg in dict.fromkeys(pkgs):
        if _package_installed(pm, pkg):
            continue
        if _package_available(pm, pkg):
            kept.append(pkg)
            continue
        console.print(f"[brand.warn][!] Package unavailable in enabled repos: {pkg}[/brand.warn]")
    return kept


def _install_build_deps(binary, pm):
    if not pm:
        return
    deps = BUILD_DEPS.get(binary, {}).get(pm, [])
    if not deps:
        return

    pkgs = _filter_installable_packages(pm, deps)
    if not pkgs:
        return

    commands = {
        "pacman": ["pacman", "-S", "--noconfirm", "--needed"] + pkgs,
        "apt": ["apt", "install", "-y"] + pkgs,
        "dnf": ["dnf", "install", "-y"] + pkgs,
    }
    cmd = commands.get(pm)
    if not cmd:
        return

    console.print(f"\n[brand.info][*] Installing build dependencies for {binary}: {' '.join(pkgs)}[/brand.info]")
    _run(cmd)


def _pkg_for_pm(binary, pm):
    idx = _PM_INDEX.get(pm, -1)
    if binary not in PKG_NAMES or idx < 0:
        return None
    return PKG_NAMES[binary][idx]


def _link_user_binary(binary, dirs):
    """Expose user-installed tools to root shells via /usr/local/bin when possible."""
    dst = os.path.join("/usr/local/bin", binary)
    with suppress(OSError):
        if os.path.islink(dst) and not os.path.exists(dst):
            os.unlink(dst)
    if os.path.exists(dst):
        return False
    for directory in dirs:
        src = os.path.join(directory, binary)
        if os.path.isfile(src) and os.access(src, os.X_OK):
            try:
                os.makedirs("/usr/local/bin", exist_ok=True)
                os.symlink(src, dst)
                _manifest_record(f"symlink:{dst}")
                console.print(f"[brand.ok][+] linked {binary} -> {dst}[/brand.ok]")
                return True
            except OSError as e:
                console.print(f"[brand.warn][!] Could not link {binary}: {e}[/brand.warn]")
                return False
    return False


def _install_direct_download(binary, spec):
    url = spec["url"]
    path = spec["path"]
    mode = spec.get("mode", 0o755)
    console.print(f"\n[brand.info][*] direct download {binary}[/brand.info]")
    console.print(f"[brand.command]  $ download {url} -> {path}[/brand.command]")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ChaosticTool-installer"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(data)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        _manifest_record(f"file:{path}")
        console.print(f"[brand.ok][+] {binary} -> {path}[/brand.ok]")
        return True
    except (OSError, urllib.error.URLError) as e:
        console.print(f"[brand.red][!] direct download failed for {binary}: {e}[/brand.red]")
        with suppress(OSError):
            os.unlink(f"{path}.tmp")
        return False


def _current_arch():
    machine = platform.machine().lower()
    aliases = {
        "arm64": "aarch64",
        "amd64": "x86_64",
    }
    return aliases.get(machine, machine)


def _github_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ChaosticTool-installer",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _extract_binary_from_tar(data, binary):
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or os.path.basename(member.name) != binary:
                    continue
                extracted = archive.extractfile(member)
                if extracted:
                    return extracted.read()
    except tarfile.TarError:
        return None
    return None


def _extract_binary_from_zip(data, binary):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = os.path.basename(info.filename)
                payload = archive.read(info)
                if name == binary:
                    return payload
                if name.endswith((".tar.gz", ".tgz")):
                    found = _extract_binary_from_tar(payload, binary)
                    if found:
                        return found
    except zipfile.BadZipFile:
        return None
    return None


def _extract_binary_from_release_asset(data, asset_name, binary):
    if asset_name.endswith(".zip"):
        found = _extract_binary_from_zip(data, binary)
        if found:
            return found
    if asset_name.endswith((".tar.gz", ".tgz")):
        found = _extract_binary_from_tar(data, binary)
        if found:
            return found
    if os.path.basename(asset_name) == binary:
        return data
    return None


def _install_release_asset(binary, spec):
    arch = _current_arch()
    wanted = spec.get("assets", {}).get(arch, [])
    if not wanted:
        console.print(f"[brand.warn][!] No release asset mapping for {binary} on {arch}[/brand.warn]")
        return False

    console.print(f"\n[brand.info][*] release asset install {binary} ({arch})[/brand.info]")
    try:
        release = _github_json(spec["api_url"])
        assets = release.get("assets", [])
        selected = None
        for wanted_name in wanted:
            selected = next((asset for asset in assets if asset.get("name") == wanted_name), None)
            if selected:
                break
        if not selected:
            names = ", ".join(asset.get("name", "") for asset in assets)
            console.print(f"[brand.warn][!] No matching release asset for {binary}. Available: {names}[/brand.warn]")
            return False

        url = selected["browser_download_url"]
        request = urllib.request.Request(url, headers={"User-Agent": "ChaosticTool-installer"})
        console.print(f"[brand.command]  $ download {url}[/brand.command]")
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()

        payload = _extract_binary_from_release_asset(data, selected["name"], spec.get("binary", binary))
        if not payload:
            console.print(f"[brand.red][!] Could not find {binary} in release asset {selected['name']}[/brand.red]")
            return False

        path = spec["path"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(payload)
        os.chmod(tmp_path, 0o755)
        os.replace(tmp_path, path)
        _manifest_record(f"file:{path}")
        console.print(f"[brand.ok][+] {binary} -> {path}[/brand.ok]")
        return True
    except (OSError, urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
        console.print(f"[brand.red][!] release asset install failed for {binary}: {e}[/brand.red]")
        with suppress(OSError):
            os.unlink(f"{spec['path']}.tmp")
        return False


def _install_source_tool(binary, spec):
    repo = spec["repo"]
    path = spec["path"]
    entry = spec["entry"]
    runner = spec.get("runner", "python3")
    wrapper = spec["wrapper"]

    console.print(f"\n[brand.info][*] source install {binary}[/brand.info]")
    if os.path.isdir(os.path.join(path, ".git")):
        ok = _run(["git", "-C", path, "pull", "--ff-only"])
    else:
        shutil.rmtree(path, ignore_errors=True)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ok = _run(["git", "clone", "--depth=1", repo, path])
    if not ok:
        return False

    entry_path = os.path.join(path, entry)
    if not os.path.isfile(entry_path):
        console.print(f"[brand.red][!] Source entrypoint missing: {entry_path}[/brand.red]")
        return False

    requirements = spec.get("requirements")
    if requirements:
        req_path = os.path.join(path, requirements)
        python_bin = shutil.which("python3")
        if python_bin and os.path.isfile(req_path):
            _run([python_bin, "-m", "pip", "install", "--break-system-packages", "-r", req_path]) or _run(
                [python_bin, "-m", "pip", "install", "-r", req_path]
            )

    try:
        os.makedirs(os.path.dirname(wrapper), exist_ok=True)
        tmp_wrapper = f"{wrapper}.tmp"
        with open(tmp_wrapper, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\n")
            fh.write(f"exec {shlex.quote(runner)} {shlex.quote(entry_path)} \"$@\"\n")
        os.chmod(tmp_wrapper, 0o755)
        os.replace(tmp_wrapper, wrapper)
        _manifest_record(f"dir:{path}")
        _manifest_record(f"file:{wrapper}")
        console.print(f"[brand.ok][+] {binary} -> {wrapper}[/brand.ok]")
        return True
    except OSError as e:
        console.print(f"[brand.red][!] wrapper creation failed for {binary}: {e}[/brand.red]")
        with suppress(OSError):
            os.unlink(f"{wrapper}.tmp")
        return False


def _install_python_module_wrapper(binary, spec):
    python_bin = shutil.which("python3")
    if not python_bin:
        console.print(f"[brand.warn][!] python3 missing; cannot create wrapper for {binary}[/brand.warn]")
        return False

    module = spec["module"]
    wrapper = spec["wrapper"]
    check = subprocess.run(
        [
            python_bin,
            "-c",
            "import importlib, sys; importlib.import_module(sys.argv[1])",
            module,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if check.returncode != 0:
        console.print(f"[brand.warn][!] Python module unavailable for {binary}: {module}[/brand.warn]")
        return False

    try:
        os.makedirs(os.path.dirname(wrapper), exist_ok=True)
        tmp_wrapper = f"{wrapper}.tmp"
        with open(tmp_wrapper, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env bash\n")
            fh.write(f"exec {shlex.quote(python_bin)} -m {shlex.quote(module)} \"$@\"\n")
        os.chmod(tmp_wrapper, 0o755)
        os.replace(tmp_wrapper, wrapper)
        _manifest_record(f"file:{wrapper}")
        console.print(f"[brand.ok][+] {binary} -> {wrapper}[/brand.ok]")
        return True
    except OSError as e:
        console.print(f"[brand.red][!] wrapper creation failed for {binary}: {e}[/brand.red]")
        with suppress(OSError):
            os.unlink(f"{wrapper}.tmp")
        return False


def _candidate_methods(binary, pm, aur_helper):
    """
    Return install methods in reliability order for this platform.

    Official packages are preferred when they exist in the enabled repos. For
    Arch security tools that are commonly absent from official repos, full mode
    falls through to Go, AUR, Cargo, release archives, Python-module wrappers,
    pipx, pip, gems, source wrappers, or direct release downloads.
    """
    candidates = []
    pkg = _pkg_for_pm(binary, pm)
    if pkg and _package_available(pm, pkg):
        candidates.append((pm, pkg, pkg))

    if binary in GO_MODULES and GO_MODULES[binary]:
        candidates.append(("go", GO_MODULES[binary], GO_MODULES[binary].split("/")[-1]))

    # _install_aur_direct does not need yay/paru; makepkg + git are enough.
    if pm == "pacman" and binary in AUR_PACKAGES:
        candidates.append(("aur", AUR_PACKAGES[binary], AUR_PACKAGES[binary]))

    if binary in CARGO_PACKAGES and CARGO_PACKAGES[binary]:
        candidates.append(("cargo", CARGO_PACKAGES[binary], CARGO_PACKAGES[binary]))

    if binary in RELEASE_ASSETS:
        candidates.append(("release", RELEASE_ASSETS[binary], "GitHub release asset"))

    if binary in PYTHON_MODULE_WRAPPERS:
        candidates.append(("pywrap", PYTHON_MODULE_WRAPPERS[binary], "python module wrapper"))

    if binary in PIPX_PACKAGES and PIPX_PACKAGES[binary]:
        candidates.append(("pipx", PIPX_PACKAGES[binary], PIPX_PACKAGES[binary]))

    if binary in PIP_PACKAGES and PIP_PACKAGES[binary]:
        candidates.append(("pip", PIP_PACKAGES[binary], PIP_PACKAGES[binary]))

    if binary in GEM_PACKAGES and GEM_PACKAGES[binary]:
        candidates.append(("gem", GEM_PACKAGES[binary], GEM_PACKAGES[binary]))

    if binary in SOURCE_INSTALLS:
        candidates.append(("source", SOURCE_INSTALLS[binary], "GitHub source"))

    if binary in DIRECT_DOWNLOADS:
        candidates.append(("direct", DIRECT_DOWNLOADS[binary], "GitHub release"))

    return candidates or [("manual", binary, "manual installation")]


def _resolve_method(binary, pm, aur_helper):
    """
    Determines the best installation method for a binary,
    based on the available package manager.
    Returns (method, package_or_module, displayed_label).
    """
    return _candidate_methods(binary, pm, aur_helper)[0]


def _method_display(candidates):
    if len(candidates) == 1:
        return candidates[0][0], candidates[0][2]
    return candidates[0][0], f"{candidates[0][2]} (alt: {', '.join(c[0] for c in candidates[1:])})"


def install_missing(missing_items, assume_yes=False, allowed_methods=None):
    """
    missing_items : list of (tool_key, binary)

    Cross-platform resolution algorithm:
      Arch            → pacman when available, otherwise Go/AUR/Cargo/release/pywrap/pipx/pip/gem/source/direct
      Debian/Ubuntu   → apt when available, otherwise Go/Cargo/release/pywrap/pipx/pip/gem/source/direct
      Everywhere      → portable installers for Go, Cargo, release archives, pywrap, pipx, pip, gems, and PEASS assets

    Root fix: makepkg and user-local installers should not write as root.
    We fork a subprocess that drops root (setuid/setgid) to become SUDO_USER
    before calling makepkg, go install, cargo install, pipx, or pip --user.
    """
    pm, aur_helper = _detect_pkg_manager()
    orig_user, orig_pw = _get_original_user()

    table = Table(title="Missing tools", border_style="brand.red", show_lines=False)
    table.add_column("Tool", style="brand.red", no_wrap=True)
    table.add_column("Method", style="brand.warn")
    table.add_column("Package / Module", style="brand.muted")

    allowed_methods = set(allowed_methods) if allowed_methods else None
    groups = {
        "pacman": [],
        "apt": [],
        "dnf": [],
        "aur": [],
        "go": [],
        "cargo": [],
        "release": [],
        "pywrap": [],
        "pipx": [],
        "pip": [],
        "gem": [],
        "source": [],
        "direct": [],
        "manual": [],
        "skipped": [],
    }
    plans = []

    for key, binary in missing_items:
        candidates = _candidate_methods(binary, pm, aur_helper)
        if allowed_methods is not None:
            candidates = [candidate for candidate in candidates if candidate[0] in allowed_methods]
        plans.append((key, binary, candidates))
        if not candidates:
            method, pkg, label = _resolve_method(binary, pm, aur_helper)
            table.add_row(binary, f"skip:{method}", label)
            groups["skipped"].append((binary, method, label))
            continue
        method, pkg, label = candidates[0]
        method_display, label_display = _method_display(candidates)
        table.add_row(binary, method_display, label_display)
        groups[method].append((binary, pkg))

    console.print(table)

    installable = [
        m for m in ("pacman", "apt", "dnf", "aur", "go", "cargo", "release", "pywrap", "pipx", "pip", "gem", "source", "direct")
        if groups[m]
    ]
    if not installable:
        console.print("\n[brand.muted]No tool can be installed automatically on this system.[/brand.muted]")
        if groups["skipped"]:
            console.print("[brand.muted]Some tools were skipped by the selected install profile.[/brand.muted]")
        return

    total = sum(len(groups[m]) for m in installable)
    console.print(f"\n[brand.warn]{total} tool(s) can be installed automatically.[/brand.warn]")
    if not assume_yes:
        try:
            rep = console.input("[brand.warn]Install now? [y/N][/brand.warn] [brand.white]›[/brand.white] ").strip().lower()
        except EOFError:
            rep = ""
        if rep != "y":
            console.print("[brand.muted]Installation skipped.[/brand.muted]")
            return

    def _pkg_cmd(method, pkgs):
        """Builds the system installation command based on the manager."""
        if method == "pacman":
            return ["pacman", "-S", "--noconfirm", "--needed"] + pkgs
        if method == "apt":
            return ["apt", "install", "-y"] + pkgs
        if method == "dnf":
            return ["dnf", "install", "-y"] + pkgs
        return None

    def _install_system_packages(method, pkgs, retry_metadata=False):
        kept = _filter_installable_packages(method, pkgs)
        if not kept:
            return False
        cmd = _pkg_cmd(method, kept)
        if not cmd:
            return False
        if _run(cmd):
            for _p in kept:
                _manifest_record(f"pkg:{method}:{_p}")
            return True
        if retry_metadata and _recover_package_metadata(method):
            kept = _filter_installable_packages(method, kept)
            if kept and _run(_pkg_cmd(method, kept)):
                return True
        if len(kept) > 1:
            console.print(f"[brand.warn][!] {method} batch failed; retrying packages individually.[/brand.warn]")
            ok = True
            for pkg in kept:
                ok = _install_system_packages(method, [pkg], retry_metadata=False) and ok
            return ok
        if method == "pacman":
            console.print(
                "[brand.warn][!] pacman still failed after refreshing databases. "
                "Your mirrorlist may be stale or temporarily out of sync.[/brand.warn]"
            )
            console.print(
                "[brand.muted]    Suggested Arch recovery: refresh mirrors, then run "
                "sudo pacman -Syyu before retrying ChaosticTool.[/brand.muted]"
            )
        return False

    def _install_runtime(binary_name, packages_by_pm):
        if shutil.which(binary_name):
            return True
        pkg = packages_by_pm.get(pm)
        if not pkg:
            return False
        if _package_installed(pm, pkg):
            return True
        if not _package_available(pm, pkg):
            console.print(f"\n[brand.warn][!] Runtime package unavailable: {pkg}[/brand.warn]")
            return False
        cmd = _pkg_cmd(pm, [pkg])
        if not cmd:
            return False
        console.print(f"\n[brand.info][*] Installing runtime dependency: {pkg}[/brand.info]")
        return _install_system_packages(pm, [pkg], retry_metadata=(pm == "pacman"))

    pipx_results = {}

    def _install_one(method, binary, pkg):
        if method in ("pacman", "apt", "dnf"):
            return _install_system_packages(method, [pkg], retry_metadata=(method == "pacman"))

        if method == "aur":
            if orig_pw is None:
                return False
            if _ensure_aur_build_prereqs(pm):
                _install_aur_direct([pkg], orig_user, orig_pw)
            return _tool_available(binary, binary)

        if method == "go":
            _install_build_deps(binary, pm)
            _install_runtime("go", {"pacman": "go", "apt": "golang", "dnf": "golang"})
            go_bin = shutil.which("go")
            if not go_bin:
                return False
            env = dict(os.environ)
            if orig_pw:
                env["HOME"] = orig_pw.pw_dir
                env["GOPATH"] = os.path.join(orig_pw.pw_dir, "go")
                env["GOBIN"] = os.path.join(orig_pw.pw_dir, "go", "bin")
                env["PATH"] = f"{env['GOBIN']}:/usr/local/go/bin:{env.get('PATH','')}"
            ok = _run([go_bin, "install", pkg], as_user_pw=orig_pw, env=env)
            if ok and orig_pw:
                _manifest_record(f"go:{os.path.join(env['GOBIN'], binary)}")
                _link_user_binary(binary, [env["GOBIN"]])
            return ok

        if method == "cargo":
            _install_build_deps(binary, pm)
            _install_runtime("cargo", {"pacman": "rust", "apt": "cargo", "dnf": "cargo"})
            cargo_bin = shutil.which("cargo")
            if not cargo_bin:
                return False
            env = dict(os.environ)
            if orig_pw:
                env["HOME"] = orig_pw.pw_dir
                env["CARGO_HOME"] = os.path.join(orig_pw.pw_dir, ".cargo")
                env["PATH"] = f"{env['CARGO_HOME']}/bin:{env.get('PATH','')}"
            ok = _run([cargo_bin, "install", pkg], as_user_pw=orig_pw, env=env)
            if ok and orig_pw:
                _manifest_record(f"cargo:{os.path.join(env['CARGO_HOME'], 'bin', binary)}")
                _link_user_binary(binary, [os.path.join(env["CARGO_HOME"], "bin")])
            return ok

        if method == "pywrap":
            return _install_python_module_wrapper(binary, pkg)

        if method == "release":
            return _install_release_asset(binary, pkg)

        if method == "pipx":
            _install_build_deps(binary, pm)
            _install_runtime("pipx", {"pacman": "python-pipx", "apt": "pipx", "dnf": "pipx"})
            pipx_bin = shutil.which("pipx")
            if not pipx_bin:
                return False
            env = dict(os.environ)
            if orig_pw:
                env["HOME"] = orig_pw.pw_dir
                env["PATH"] = f"{orig_pw.pw_dir}/.local/bin:{env.get('PATH','')}"
                env["PIPX_HOME"] = os.path.join(orig_pw.pw_dir, ".local", "share", "pipx")
                env["PIPX_BIN_DIR"] = os.path.join(orig_pw.pw_dir, ".local", "bin")
            if pkg not in pipx_results:
                pipx_results[pkg] = _run([pipx_bin, "install", "--force", pkg], as_user_pw=orig_pw, env=env)
                if pipx_results[pkg]:
                    _manifest_record(f"pipx:{_PIPX_CANONICAL.get(pkg, pkg)}")
            if pipx_results[pkg] and orig_pw:
                _link_user_binary(binary, [os.path.join(orig_pw.pw_dir, ".local", "bin")])
            return pipx_results[pkg]

        if method == "pip":
            _install_build_deps(binary, pm)
            _install_runtime("pip3", {"pacman": "python-pip", "apt": "python3-pip", "dnf": "python3-pip"})
            python_bin = shutil.which("python3")
            if not python_bin:
                return False
            env = dict(os.environ)
            if orig_pw:
                env["HOME"] = orig_pw.pw_dir
                env["PATH"] = f"{orig_pw.pw_dir}/.local/bin:{env.get('PATH','')}"
            ok = _run([python_bin, "-m", "pip", "install", "--user", "--break-system-packages", pkg], as_user_pw=orig_pw, env=env)
            if ok and orig_pw:
                _link_user_binary(binary, [os.path.join(orig_pw.pw_dir, ".local", "bin")])
            return ok

        if method == "gem":
            _install_build_deps(binary, pm)
            _install_runtime("gem", {"pacman": "ruby", "apt": "ruby-full", "dnf": "ruby"})
            gem_bin = shutil.which("gem")
            if gem_bin and _run([gem_bin, "install", pkg]):
                _manifest_record(f"gem:{pkg}")
                return True
            return False

        if method == "source":
            _install_build_deps(binary, pm)
            return _install_source_tool(binary, pkg)

        if method == "direct":
            return _install_direct_download(binary, pkg)

        return False

    # --- official system packages (pacman/apt/dnf) — direct root ---
    for pm_method in ("pacman", "apt", "dnf"):
        if groups[pm_method]:
            if pm_method == "apt":
                _refresh_package_metadata(pm_method)
            pkgs = [p for _, p in groups[pm_method]]
            console.print(f"\n[brand.info][*] {pm_method} : {' '.join(dict.fromkeys(pkgs))}[/brand.info]")
            if not _install_system_packages(pm_method, pkgs, retry_metadata=(pm_method == "pacman")):
                console.print(f"[brand.warn][!] Some {pm_method} packages failed to install.[/brand.warn]")

    for binary, _ in groups["go"] + groups["cargo"] + groups["pipx"] + groups["pip"] + groups["gem"] + groups["source"]:
        _install_build_deps(binary, pm)

    # --- AUR (Arch only) — build as user, install as root (no sudoers needed) ---
    if groups["aur"]:
        pkgs = list({p for _, p in groups["aur"]})
        if orig_pw is None:
            console.print("\n[bright_yellow][!] Run without sudo — SUDO_USER unknown.[/bright_yellow]")
            console.print("[brand.muted]    Re-run with: sudo ./install.sh[/brand.muted]")
        else:
            if _ensure_aur_build_prereqs(pm):
                _install_aur_direct(pkgs, orig_user, orig_pw)

    # --- go install — drop root, GOPATH of the original user ---
    if groups["go"]:
        _install_runtime("go", {"pacman": "go", "apt": "golang", "dnf": "golang"})
        go_bin = shutil.which("go")
        if not go_bin:
            console.print("\n[bright_yellow][!] go missing.[/bright_yellow]")
            console.print("[brand.muted]    Arch: sudo pacman -S go | Debian: sudo apt install golang[/brand.muted]")
            for binary, module in groups["go"]:
                console.print(f"[brand.muted]    Then: go install {module}[/brand.muted]")
        else:
            for binary, module in groups["go"]:
                console.print(f"\n[brand.info][*] go install {module}[/brand.info]")
                env = dict(os.environ)
                if orig_pw:
                    env["HOME"]   = orig_pw.pw_dir
                    env["GOPATH"] = os.path.join(orig_pw.pw_dir, "go")
                    env["GOBIN"]  = os.path.join(orig_pw.pw_dir, "go", "bin")
                    env["PATH"]   = f"{env['GOBIN']}:/usr/local/go/bin:{env.get('PATH','')}"
                if _run([go_bin, "install", module], as_user_pw=orig_pw, env=env):
                    console.print(f"[brand.ok][+] {binary} -> ~/go/bin/[/brand.ok]")
                    if orig_pw:
                        _manifest_record(f"go:{os.path.join(env['GOBIN'], binary)}")
                        _link_user_binary(binary, [env["GOBIN"]])

    # --- cargo install — drop root, Cargo home of the original user ---
    if groups["cargo"]:
        _install_runtime("cargo", {"pacman": "rust", "apt": "cargo", "dnf": "cargo"})
        cargo_bin = shutil.which("cargo")
        if not cargo_bin:
            console.print("\n[bright_yellow][!] cargo missing.[/bright_yellow]")
            for binary, pkg in groups["cargo"]:
                console.print(f"[brand.muted]    Then: cargo install {pkg}[/brand.muted]")
        else:
            for binary, pkg in groups["cargo"]:
                console.print(f"\n[brand.info][*] cargo install {pkg}[/brand.info]")
                env = dict(os.environ)
                if orig_pw:
                    env["HOME"] = orig_pw.pw_dir
                    env["CARGO_HOME"] = os.path.join(orig_pw.pw_dir, ".cargo")
                    env["PATH"] = f"{env['CARGO_HOME']}/bin:{env.get('PATH','')}"
                if _run([cargo_bin, "install", pkg], as_user_pw=orig_pw, env=env):
                    console.print(f"[brand.ok][+] {binary} -> ~/.cargo/bin/[/brand.ok]")
                    if orig_pw:
                        _manifest_record(f"cargo:{os.path.join(env['CARGO_HOME'], 'bin', binary)}")
                        _link_user_binary(binary, [os.path.join(env["CARGO_HOME"], "bin")])

    # --- Python module wrappers for distro packages that expose modules but not every script name ---
    if groups["pywrap"]:
        for binary, spec in groups["pywrap"]:
            _install_python_module_wrapper(binary, spec)

    # --- release archive downloads ---
    if groups["release"]:
        for binary, spec in groups["release"]:
            _install_release_asset(binary, spec)

    # --- pipx install (isolated Python CLI tools) ---
    if groups["pipx"]:
        _install_runtime("pipx", {"pacman": "python-pipx", "apt": "pipx", "dnf": "pipx"})
        pipx_bin = shutil.which("pipx")
        if not pipx_bin:
            console.print("\n[bright_yellow][!] pipx missing.[/bright_yellow]")
            for binary, pkg in groups["pipx"]:
                console.print(f"[brand.muted]    Then: pipx install {pkg}[/brand.muted]")
        else:
            pipx_results = {}
            for binary, pkg in groups["pipx"]:
                if pkg not in pipx_results:
                    console.print(f"\n[brand.info][*] pipx install {pkg}[/brand.info]")
                    env = dict(os.environ)
                    if orig_pw:
                        env["HOME"] = orig_pw.pw_dir
                        env["PATH"] = f"{orig_pw.pw_dir}/.local/bin:{env.get('PATH','')}"
                        env["PIPX_HOME"] = os.path.join(orig_pw.pw_dir, ".local", "share", "pipx")
                        env["PIPX_BIN_DIR"] = os.path.join(orig_pw.pw_dir, ".local", "bin")
                    pipx_results[pkg] = _run([pipx_bin, "install", "--force", pkg], as_user_pw=orig_pw, env=env)
                    if pipx_results[pkg]:
                        _manifest_record(f"pipx:{_PIPX_CANONICAL.get(pkg, pkg)}")
                if pipx_results[pkg] and orig_pw:
                    _link_user_binary(binary, [os.path.join(orig_pw.pw_dir, ".local", "bin")])

    # --- pip install (cross-platform) ---
    if groups["pip"]:
        _install_runtime("pip3", {"pacman": "python-pip", "apt": "python3-pip", "dnf": "python3-pip"})
        python_bin = shutil.which("python3")
        for binary, pkg in groups["pip"]:
            console.print(f"\n[brand.info][*] pip install {pkg}[/brand.info]")
            if python_bin:
                env = dict(os.environ)
                if orig_pw:
                    env["HOME"] = orig_pw.pw_dir
                    env["PATH"] = f"{orig_pw.pw_dir}/.local/bin:{env.get('PATH','')}"
                if _run([python_bin, "-m", "pip", "install", "--user", "--break-system-packages", pkg], as_user_pw=orig_pw, env=env) and orig_pw:
                    _link_user_binary(binary, [os.path.join(orig_pw.pw_dir, ".local", "bin")])
            else:
                console.print("[bright_yellow][!] python3 missing.[/bright_yellow]")

    # --- gem install (Ruby-based tools) ---
    if groups["gem"]:
        _install_runtime("gem", {"pacman": "ruby", "apt": "ruby-full", "dnf": "ruby"})
        gem_bin = shutil.which("gem")
        if not gem_bin:
            console.print("\n[bright_yellow][!] gem missing.[/bright_yellow]")
            for binary, pkg in groups["gem"]:
                console.print(f"[brand.muted]    Then: gem install {pkg}[/brand.muted]")
        else:
            for binary, pkg in groups["gem"]:
                console.print(f"\n[brand.info][*] gem install {pkg}[/brand.info]")
                if _run([gem_bin, "install", pkg]):
                    _manifest_record(f"gem:{pkg}")

    # --- source checkouts with stable local wrappers ---
    if groups["source"]:
        for binary, spec in groups["source"]:
            _install_source_tool(binary, spec)

    # --- direct portable downloads ---
    if groups["direct"]:
        for binary, spec in groups["direct"]:
            _install_direct_download(binary, spec)

    # --- fallback methods for tools still missing after their preferred method ---
    for key, binary, candidates in plans:
        if not candidates or _tool_available(key, binary):
            continue
        for method, pkg, label in candidates[1:]:
            if method == "manual":
                continue
            console.print(f"\n[brand.warn][!] {binary} still missing; trying fallback {method}: {label}[/brand.warn]")
            _install_one(method, binary, pkg)
            if _tool_available(key, binary):
                break

    # --- manual ---
    if groups["manual"]:
        console.print("\n[bright_yellow][!] Tools to install manually:[/bright_yellow]")
        for binary, _ in groups["manual"]:
            console.print(f"  [brand.muted]- {binary}[/brand.muted]")

    unresolved = [(key, binary) for key, binary, _ in plans if not _tool_available(key, binary)]
    if unresolved:
        console.print("\n[bright_yellow][!] Still missing after automatic attempts:[/bright_yellow]")
        for _, binary in unresolved:
            console.print(f"  [brand.muted]- {binary}[/brand.muted]")
