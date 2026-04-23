import os
import re
from typing import Any
from dataclasses import dataclass


@dataclass
class SteamSession:
    """Steam login session data"""

    steam_id: str
    account_name: str
    persona_name: str
    most_recent: bool = False


def find_steam_path() -> str | None:
    # 기본 경로들 (우선순위)
    possible_paths = [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # 레지스트리 fallback
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        return steam_path
    except:
        pass

    return None


def get_vdf_content() -> str | None:
    steam_path = find_steam_path()
    if not steam_path:
        return None

    vdf_path = os.path.join(steam_path, "config", "loginusers.vdf")

    if not os.path.exists(vdf_path):
        return None

    with open(vdf_path, "r", encoding="utf-8") as f:
        return f.read()


def parse_vdf(vdf_content: str) -> dict[str, Any]:
    """Simple VDF parser for loginusers.vdf."""
    result = {}
    stack = [result]
    last_key = None

    # Matches "key" "value" OR "key"
    pattern = re.compile(r'"([^"]*)"(?:\s*"([^"]*)")?')

    for line in vdf_content.splitlines():
        line = line.strip()
        if not line or line.startswith(("//", "#")):
            continue

        if line == "{":
            if last_key:
                new_dict = {}
                stack[-1][last_key] = new_dict
                stack.append(new_dict)
                last_key = None
            continue

        if line == "}":
            if len(stack) > 1:
                stack.pop()
            continue

        match = pattern.search(line)
        if match:
            key, value = match.groups()
            if value is not None:
                stack[-1][key] = value
                last_key = None
            else:
                last_key = key
                if "{" in line:
                    new_dict = {}
                    stack[-1][last_key] = new_dict
                    stack.append(new_dict)
                    last_key = None

    return result


def get_most_recent_steam_id() -> str | None:
    content = get_vdf_content()
    if not content:
        return None

    data = parse_vdf(content)
    logins = data.get("users", {})

    for steam_id, user_data in logins.items():
        if user_data.get("MostRecent") == "1":
            return steam_id

    return None


def mask_steam_id(steam_id: str | None) -> str:
    if not steam_id:
        return "(none)"
    steam_id = str(steam_id).strip()
    if len(steam_id) <= 8:
        return "***"
    return f"{steam_id[:4]}...{steam_id[-4:]}"


def get_all_steam_sessions() -> list[SteamSession]:
    content = get_vdf_content()
    if not content:
        return []

    data = parse_vdf(content)
    logins = data.get("users", {})

    sessions = []
    for steam_id, user_data in logins.items():
        sessions.append(SteamSession(
            steam_id=steam_id,
            account_name=user_data.get("AccountName", ""),
            persona_name=user_data.get("PersonaName", ""),
            most_recent=(user_data.get("MostRecent") == "1"),
        ))

    return sessions


if __name__ == "__main__":
    sessions = get_all_steam_sessions()
    for s in sessions:
        print(s)
