"""
Tezkor tugma kodini tekshirish — client qulfi bilan AYNAN bir xil lug'at.

Client (`client/services/lockdown.py`) kodni `_normalize` + `_parse_combo`
bilan o'qiydi va TANIMAGAN kodni faqat log'ga yozib, BLOKLAMAYDI. Ya'ni
panelda xato yozilgan kod (`pageup`, `leftalt`) imtihonda jimgina ochiq
qolardi — administrator esa "bloklangan" deb o'ylardi. Shuning uchun
server kodni saqlashdan OLDIN client qoidasi bilan tekshiradi va kanonik
shaklda yozadi.

Lug'at client'dagi `_KEY_ALIASES`, `_MODIFIER_VKS`, `_NAMED_VKS` va
`_NEVER_BLOCKED` ning nusxasi (VK qiymatlarisiz — server ularni
ishlatmaydi). Client'da yangi tugma nomi qo'shilsa, shu yerga HAM va
`frontend/src/utils/hotkeys.js` ga qo'shing.
"""

from __future__ import annotations

KEY_ALIASES = {
    "printscreen": "print screen",
    "prtsc": "print screen",
    "prt sc": "print screen",
    "prtscr": "print screen",
    "prnt scrn": "print screen",
    "escape": "esc",
    "windows": "win",
    "meta": "win",
    "super": "win",
    "cmd": "win",
    "del": "delete",
    "ins": "insert",
    "pgup": "page up",
    "pgdn": "page down",
    "return": "enter",
    "capslock": "caps lock",
    "numlock": "num lock",
    "scrolllock": "scroll lock",
    "spacebar": "space",
    "arrow up": "up",
    "arrow down": "down",
    "arrow left": "left",
    "arrow right": "right",
    "plus": "=",
    "minus": "-",
}

#: Chiqishning yagona yo'li — client uni ro'yxatda bo'lsa ham bloklamaydi.
NEVER_BLOCKED = frozenset({"ctrl+q"})

MODIFIERS = frozenset({
    "alt", "left alt", "right alt", "alt gr",
    "ctrl", "control", "left ctrl", "right ctrl",
    "shift", "left shift", "right shift",
    "win", "left windows", "right windows",
})

NAMED_KEYS = frozenset(
    {
        "backspace", "tab", "enter", "pause", "caps lock", "esc", "space",
        "page up", "page down", "end", "home", "left", "up", "right", "down",
        "print screen", "insert", "delete", "apps", "menu",
        "num *", "num +", "num -", "num .", "num /", "num lock", "scroll lock",
        ";", "=", ",", "-", ".", "/", "`", "[", "\\", "]", "'",
    }
    | {f"num {i}" for i in range(10)}
    | {f"f{i}" for i in range(1, 25)}
)


def normalize(code: str) -> str:
    """`Ctrl + Shift+I` -> `ctrl+shift+i` (client `_normalize` bilan bir xil)."""
    parts = [part.strip().lower() for part in str(code or "").split("+")]
    parts = [KEY_ALIASES.get(part, part) for part in parts if part]
    return "+".join(parts)


def _is_key(name: str) -> bool:
    if name in MODIFIERS or name in NAMED_KEYS:
        return True
    return len(name) == 1 and ("a" <= name <= "z" or "0" <= name <= "9")


def clean_hotkey(code: str) -> str:
    """
    Kanonik kod yoki `ValueError` (o'zbekcha sabab bilan).

    Qoidalar client `_parse_combo` dagi bilan bir xil: har qism ma'lum
    tugma, takror yo'q, modifikator bo'lmagan asosiy tugma ko'pi bilan
    bitta. `ctrl+q` rad etiladi — client uni baribir o'tkazib yuboradi.
    """
    canonical = normalize(code)
    if not canonical:
        raise ValueError("Kombinatsiyani kiriting, masalan: alt+tab")
    parts = canonical.split("+")
    unknown = [part for part in parts if not _is_key(part)]
    if unknown:
        raise ValueError(
            "Client bu tugmani tanimaydi: " + ", ".join(f"«{part}»" for part in unknown)
        )
    if len(set(parts)) != len(parts):
        raise ValueError("Bir tugma ikki marta yozilgan")
    if len([part for part in parts if part not in MODIFIERS]) > 1:
        raise ValueError(
            "Faqat bitta asosiy tugma bo'lishi mumkin (qolganlari Ctrl/Alt/Shift/Win)"
        )
    if canonical in NEVER_BLOCKED:
        raise ValueError("Ctrl+Q bloklanmaydi — bu dasturdan chiqishning yagona yo'li")
    return canonical
