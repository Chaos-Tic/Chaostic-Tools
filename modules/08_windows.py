from core import ui

TOOLS = ["secretsdump.py", "psexec.py", "GetUserSPNs.py", "crackmapexec", "bloodhound-python"]


def run():
    ui.category_menu("Windows / Active Directory", TOOLS)
