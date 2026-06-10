<div align="center">

<img src="Banner.png" alt="ChaosticTool - Red Ops Control Surface" width="100%" />

# ChaosticTool

### Linux pentest control surface for structured recon, tool orchestration, routing control, and target-based evidence capture

[![Version](https://img.shields.io/badge/version-1.3.1-ff3131?style=for-the-badge)](https://github.com/Chaos-Tic/Chaostic-Tool/releases/tag/v1.3.1)
[![Python](https://img.shields.io/badge/python-3.11%2B-111827?style=for-the-badge&logo=python)](https://www.python.org/)
[![UI](https://img.shields.io/badge/UI-Rich%20Terminal-ff3131?style=for-the-badge)](https://github.com/Textualize/rich)
[![Platform](https://img.shields.io/badge/platform-Linux-111827?style=for-the-badge&logo=linux)](#supported-systems)
[![License](https://img.shields.io/badge/license-MIT-111827?style=for-the-badge)](LICENSE)

ChaosticTool is a Rich-powered terminal framework for authorized security testing. It centralizes common pentest tools, guided scan flows, target-aware output storage, and Tor/VPN routing controls into one fast interactive CLI.

</div>

---

## Screenshots

<p align="center">
  <img width="1896" height="782" alt="image" src="https://github.com/user-attachments/assets/cd667ae3-bab3-4b77-a441-a01f1888d85a" />
</p>

## What Is Chaostic Tool?

ChaosticTool is a vibe-coded pentesting framework: an operator-first CLI built around real security testing workflows and fast iteration. It brings a broad set of reconnaissance, enumeration, scanning, exploitation-support, post-exploitation, password, wireless, and network tools into one structured terminal experience.

The goal is not to hide what the underlying tools do. The goal is to make them faster to launch, easier to organize, safer to route, and cleaner to document during an assessment.

ChaosticTool gives you:

- one target context shared across modules;
- curated presets for common attack and recon steps;
- guided attack flows for repeatable multi-tool chains;
- automatic result storage by target and category;
- Tor/proxy and VPN guard visibility before launching tools;

## Why ChaosticTool

Most security testing sessions become messy fast: repeated commands, scattered outputs, forgotten flags, and unclear routing state. ChaosticTool is built to keep the operator focused by turning a Linux workstation into a structured terminal control surface.

It does not replace the underlying tools. It orchestrates them cleanly.

## Core Features

- Rich-based terminal UI with a persistent HUD for target, route, proxy, and version state.
- Phase-based methodology: OSINT, network scan, web enum, vuln scan, exploitation, post-exploitation, passwords, wireless, and MITM.
- Ready-to-run presets for tools such as `nmap`, `rustscan`, `gobuster`, `ffuf`, `httpx`, `nuclei`, `sqlmap`, `hydra`, `bettercap`, and more.
- Target-aware result storage under `targets/<target>/`.
- Guided attack flows for basic, intermediate, and advanced recon chains.
- Tor routing through `proxychains` where operationally appropriate.
- VPN guard for `tun*`, `wg*`, and `ppp*` interfaces.
- Live execution feedback, command launch panels, exit summaries, and saved-result indicators.
- Startup tool check with optional installation of missing dependencies.
- Clean interrupt handling: `Ctrl+C` stops the running tool without leaving ChaosticTool child processes behind.

## Supported Systems

ChaosticTool targets Linux distributions commonly used for security work:

| Family | Status | Notes |
| --- | --- | --- |
| Arch / Manjaro | Supported | Uses `pacman`; full profile builds AUR packages directly with `makepkg` after installing `pacman`, `git`, and `base-devel`. |
| Debian / Ubuntu | Supported | Uses `apt`. |
| Kali / Parrot | Supported | Debian-based workflow. |
| Fedora | Supported | Uses `dnf`. |

Several integrated tools require elevated privileges, so ChaosticTool is intended to run with `sudo`.

## Installation

```bash
git clone https://github.com/Chaos-Tic/Chaostic-Tool.git
cd Chaostic-Tool
sudo ./install.sh
sudo chaostictool
```

The default installer uses the `standard` profile: it installs the Python runtime, `rich`, the ChaosticTool launcher, and fast official distro packages where available. It deliberately avoids source builds and large optional stacks by default.

Supported installer options:

```bash
sudo ./install.sh --profile minimal      # Python/Rich + launcher only
sudo ./install.sh --profile standard     # default: official distro packages only
sudo ./install.sh --with-tor             # Tor/proxychains for minimal/standard profiles
sudo ./install.sh --profile full         # heavy Go/Cargo/pipx/pip/gem/source/AUR installs + Tor routing
```

The installer detects `pacman`, `apt`, `dnf`, `zypper`, or `apk`, skips unavailable packages instead of failing the whole run, and links registered user-installed Go, Cargo, pipx, pip, and local binaries into paths visible from root shells.

On ARM systems such as Raspberry Pi OS, the `full` profile uses portable fallbacks for tools that are often absent from the default repositories. Metasploit can still remain unavailable unless the system exposes a compatible `metasploit-framework` package.

## Uninstallation

```bash
sudo ./uninstall.sh
```

The uninstaller removes, in order:

- the `/usr/local/bin/chaostictool` launcher;
- source-install wrappers (`responder`, `whatweb`, `xsstrike`) and Python-module wrappers (`secretsdump.py`, `psexec.py`, `GetUserSPNs.py`) from `/usr/local/bin`;
- direct-download assets (`linpeas.sh`, `winpeas.exe`, `rustscan` release binary);
- symlinks to user-local tool directories (`~/go/bin`, `~/.cargo/bin`, `~/.local/bin`) that the installer created;
- the `/opt/chaostictool/` source checkouts and `/var/cache/chaostictool/` build staging area;
- Tor and proxychains config modifications, restoring originals from the `.chaostictool.bak` backups.

For Go, Cargo, pipx, and gem tools, the uninstaller asks for confirmation before removing each group. System packages installed via `pacman`, `apt`, or `dnf` are listed at the end for manual review — they are never removed automatically.

The project directory itself is not touched. Remove it manually once the uninstaller has run:

```bash
sudo rm -rf Chaostic-Tool/
```

## Quick Start

1. Launch ChaosticTool:

```bash
sudo chaostictool
```

2. Select `0` to configure a target.

3. Move through the methodology:

```text
1  OSINT & Passive Recon
2  Network Scan
3  Web Enumeration
4  Vulnerability Scan
5  Exploitation
6  Post-Exploitation & Privesc
7  Password Cracking
8  Windows / Active Directory
9  Wireless Security
10 Network & MITM
```

4. Use `11` to browse saved results.

5. Use `12` to run guided attack flows.

6. Use `p` to control Proxy / VPN / Tor routing.

Navigation:

```text
r / 0     back
Ctrl+C    interrupt the running tool
99        quit from main menu
```

## Routing Model

ChaosticTool is explicit about routing. The banner and each tool launch show the active route state:

```text
DIRECT
TOR via proxychains
VPN <interface>
VPN guard <interface> (default: <route>)
```

### Tor Mode

Tor mode wraps compatible internet-facing tools with `proxychains`. ChaosticTool avoids routing local, wireless, packet-capture, cracking, payload-generation, or network-interface tools through Tor when that would be operationally wrong or misleading.

The Tor menu can:

- enable Tor routing;
- check Tor service status;
- show the current Tor exit IP;
- rotate Tor identity;
- enable automatic rotation before every Tor-routed tool.

If ChaosticTool starts Tor itself, it stops that Tor service on exit or interrupt.

### VPN Guard

VPN mode does not force Linux traffic through a specific interface. The kernel routing table still decides. ChaosticTool acts as a guard:

- detects `tun*`, `wg*`, and `ppp*` interfaces;
- shows the selected VPN interface;
- warns when the default route is not using that interface.

## Result Storage

The repository ships with an empty `targets/` directory. Real scan outputs are ignored by Git.

After target configuration, ChaosticTool creates a structured workspace:

```text
targets/
└── example.com/
    ├── osint/
    ├── recon/
    ├── web_enum/
    ├── vulnscan/
    ├── exploitation/
    ├── postexploit/
    ├── passwords/
    ├── wireless/
    └── network/
```

Example outputs:

```text
targets/example.com/osint/dig_a_example.com.txt
targets/example.com/recon/nmap_rapide_example.com.txt
targets/example.com/web_enum/ffuf_dir_example.com.txt
```

## Included Categories

| Category | Example tools |
| --- | --- |
| OSINT & Passive Recon | `whois`, `dig`, `subfinder`, `amass`, `dnsrecon`, `theHarvester`, `shodan` |
| Network Scan | `nmap`, `rustscan`, `masscan`, `naabu` |
| Web Enumeration | `gobuster`, `ffuf`, `httpx`, `wafw00f`, `whatweb`, `katana`, `gau`, `waybackurls` |
| Vulnerability Scan | `nikto`, `nuclei`, `wpscan`, `testssl.sh`, `sslscan` |
| Exploitation | `sqlmap`, `xsstrike`, `dalfox`, `metasploit`, `msfvenom` |
| Post-Exploitation | `linpeas`, `winpeas`, `impacket`, `crackmapexec`, `bloodhound-python` |
| Password Cracking | `hashcat`, `john`, `hydra` |
| Wireless Security | `airmon-ng`, `airodump-ng`, `aircrack-ng`, `reaver`, `wifite` |
| Network & MITM | `bettercap`, `ettercap`, `tcpdump`, `responder` |

## Project Structure

```text
chaostictool.py      # entry point, root check, main navigation
core/tools.py        # tool registry, presets, categories
core/ui.py           # Rich UI, menus, banner, startup checks
core/executor.py     # process execution, progress, output saving
core/proxy.py        # Tor, VPN guard, proxychains routing logic
core/installer.py    # dependency and tool installation resolver
core/target.py       # target normalization and result directories
core/session.py      # result browser and cleanup
core/flows.py        # guided attack flows
modules/             # category entry points
targets/             # empty in Git; local results are ignored
```

## Adding A Tool

Tool definitions live in `core/tools.py`.

```python
"my_tool": {
    "name": "My Tool",
    "binary": "my-tool",
    "desc": "Short description",
    "category": "recon",
    "output_dir": "recon",
    "requires_root": False,
    "presets": [
        {
            "label": "Quick scan",
            "cmd": ["my-tool", "{host}"],
            "output": "mytool_quick",
        },
    ],
}
```

Available placeholders:

```text
{host}
{url}
{port}
{wordlist}
```

Presets can also define custom prompt fields through `"prompt"`.

## Release

Current release: `v1.3.1`.

See releases: https://github.com/Chaos-Tic/Chaostic-Tool/releases

## License

MIT. See [LICENSE](LICENSE).
