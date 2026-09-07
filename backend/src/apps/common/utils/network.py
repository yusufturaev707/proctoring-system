"""
Tarmoq manzillari bilan ishlash.

Bitta joyda, chunki "bu manzil tashqi (NAT) manzilmi yoki bino ichidagi
LAN manzilmi?" degan savol tizimda bir necha joyda beriladi: qurilma
ro'yxatdan o'tishda, ishga tushishdagi preflight tekshiruvida va
diagnostikada. Har birida alohida yozilsa, ular vaqt o'tib bir-biridan
ajralib ketadi.
"""

from __future__ import annotations

import ipaddress


def is_private_ip(ip_address: str) -> bool:
    """
    Manzil bino ICHIDAGI (yoki serverning o'zidagi) manzilmi?

    `True` — bu manzil binoni aniqlash uchun yaramaydi: 192.168.x.x
    har bir binoda takrorlanadi, 127.0.0.1 esa serverning o'zi.

    Yaroqsiz satr ham `True` qaytaradi: noma'lum qiymatga "tashqi
    manzil" deb ishonish, uni bilmaslikdan xavfliroq.
    """
    try:
        parsed = ipaddress.ip_address(str(ip_address or "").strip())
    except ValueError:
        return True
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_unspecified
    )


def is_public_ip(ip_address: str) -> bool:
    return not is_private_ip(ip_address)
