#!/usr/bin/env python3
import atexit
import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core import ui
    from core import target as tgt
    from core import session
    from core import proxy
    from core import flows
    from core import executor
except ImportError as e:
    print(f"\n[!] Missing dependency: {e}")
    print("    Install with: pip3 install -r requirements.txt\n")
    sys.exit(1)


def load_module(filename):
    return importlib.import_module(f"modules.{filename}")


MODULES = {
    "1":  "01_osint",
    "2":  "02_recon",
    "3":  "03_web_enum",
    "4":  "04_vulnscan",
    "5":  "05_exploitation",
    "6":  "06_postexploit",
    "7":  "07_passwords",
    "8":  "08_windows",
    "9":  "09_wireless",
    "10": "10_network",
}


def configure_target():
    ui.header("Configure target")
    if tgt.is_defined():
        ui.console.print(f"[brand.muted]Current target:[/brand.muted] [brand.ok]{tgt.summary()}[/brand.ok]\n")
    host = ui.ask("Host / domain / IP", tgt.TARGET["host"] or None)
    url = ui.ask("URL (optional, otherwise derived from host)", tgt.TARGET["url"] or None)
    port = ui.ask("Port", tgt.TARGET["port"])
    d = tgt.set_target(host=host, url=url, port=port)
    ui.console.print(f"\n[brand.ok][+] Target set:[/brand.ok] [brand.white]{tgt.summary()}[/brand.white]")
    if d:
        ui.console.print(f"[brand.ok][+] Directory:[/brand.ok] [brand.command]{d}[/brand.command]")
    ui.pause()


MAIN_ENTRIES = [
    ("0",  "Configure target",               "brand.red",  "sets host/URL/port and creates the results folder", "[brand.red]SETUP[/brand.red]"),
    ("1",  "OSINT & Passive Recon",          "brand.ok",   "whois, dig, subfinder, amass, dnsrecon, theHarvester, shodan", "[brand.ok]PHASE 01[/brand.ok]"),
    ("2",  "Network Scan",                   "brand.ok",   "nmap, rustscan, masscan, naabu", "[brand.ok]PHASE 02[/brand.ok]"),
    ("3",  "Web Enumeration",                "brand.ok",   "gobuster, ffuf, httpx, wafw00f, whatweb, katana, gau, waybackurls", "[brand.ok]PHASE 03[/brand.ok]"),
    ("4",  "Vulnerability Scan",             "brand.ok",   "nikto, nuclei, wpscan, testssl, sslscan", "[brand.ok]PHASE 04[/brand.ok]"),
    ("5",  "Exploitation",                   "brand.ok",   "sqlmap, xsstrike, dalfox, metasploit, msfvenom", "[brand.ok]PHASE 05[/brand.ok]"),
    ("6",  "Post-Exploitation & Privesc",    "brand.ok",   "linpeas, impacket, crackmapexec, bloodhound", "[brand.ok]PHASE 06[/brand.ok]"),
    ("7",  "Password Cracking",              "brand.ok",   "hashcat, john, hydra", "[brand.ok]PHASE 07[/brand.ok]"),
    ("8",  "Windows / Active Directory",     "brand.ok",   "secretsdump, psexec, kerberoasting, nxc, bloodhound", "[brand.ok]AD[/brand.ok]"),
    ("9",  "Wireless Security",              "brand.ok",   "airmon-ng, airodump-ng, aircrack-ng, reaver, wifite", "[brand.ok]RF[/brand.ok]"),
    ("10", "Network & MITM",                 "brand.ok",   "bettercap, ettercap, tcpdump, responder", "[brand.ok]LAN[/brand.ok]"),
    ("11", "Results & Session",              "brand.info", "browse files in the target folder", "[brand.info]FILES[/brand.info]"),
    ("12", "Attack flows",                   "brand.info", "guided basic/intermediate/advanced attack chains", "[brand.info]FLOW[/brand.info]"),
    ("p",  "Proxy / VPN / Tor",              "brand.warn", "route traffic through Tor or guard a VPN interface", "[brand.warn]ROUTE[/brand.warn]"),
    ("w",  "Wordlists",                       "brand.info", "download missing wordlists (SecLists, rockyou, dirb)", "[brand.info]WORDS[/brand.info]"),
    ("99", "Quit",                           "bright_red", "", "[bright_red]EXIT[/bright_red]"),
]


def main_menu():
    return ui.menu("Main Menu", MAIN_ENTRIES, footer_extra=ui.context_footer(), show_back=False)


def main():
    if os.geteuid() != 0:
        print("\n[!] This script requires root privileges.")
        print("    Re-run with: sudo python3 chaostictool.py\n")
        sys.exit(1)

    flows.load_custom_flows()
    ui.startup_check()
    while True:
        choice = main_menu()
        if choice == "0":
            configure_target()
        elif choice.lower() == "p":
            proxy.proxy_menu(ui)
        elif choice.lower() == "w":
            from core import wordlists as _wl
            _wl.wordlist_menu()
        elif choice == "11":
            session.view_results()
        elif choice == "12":
            flows.flow_menu()
        elif choice in MODULES:
            try:
                mod = load_module(MODULES[choice])
                mod.run()
            except Exception as e:
                ui.console.print(f"[bright_red][!] Module error: {e}[/bright_red]")
                ui.pause()
        elif choice == "99":
            ui.console.print("\n[brand.red]ChaosticTool session closed.[/brand.red]\n")
            sys.exit(0)
        else:
            ui.console.print("[bright_red]Invalid choice.[/bright_red]")
            ui.pause()


def cleanup():
    executor.cleanup_processes()
    proxy.cleanup_proxy()


if __name__ == "__main__":
    atexit.register(cleanup)
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
        cleanup()
        sys.exit(0)
