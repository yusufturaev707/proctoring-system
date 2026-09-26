"""
Tarmoq adapteri — Windows API orqali (`iphlpapi.dll`).

NIMA UCHUN AYNAN WinAPI. `system_info.py` dagi zaxira usullar
(psutil, `getmac`, `route print`) ikkita savolga ALOHIDA javob
beradi: "MAC qanday" va "IP qanday". Ular BOSHQA-BOSHQA
adapterdan kelib qolishi mumkin va imtihon markazidagi tipik
mashinada bu muqarrar — Hyper-V, WSL, VMware va VPN adapterlari
bir vaqtda "ulangan" holatda turadi. Natijada server MAC bo'yicha
bitta mashinani, IP bo'yicha boshqasini ko'rardi va nomuvofiqlik
faqat inventarizatsiyani solishtirganda ma'lum bo'lardi.

Bu modul boshqa yo'ldan boradi: avval OS'dan **qaysi adapter
orqali serverga chiqiladi** deb so'raydi (`GetBestInterface` —
marshrut jadvalidagi haqiqiy qaror), keyin AYNAN o'sha
adapterning MAC va IPv4 manzilini oladi
(`GetAdaptersAddresses`). Ya'ni ikkala qiymat bitta manbadan
keladi va ular doimo bir-biriga mos.

Bu qaror MAC bo'yicha tekshiruvning asosi: server "shu binoda
shu MAC bormi?" degan savolga javob beradi va client noto'g'ri
adapterni yuborsa, to'g'ri ro'yxatga olingan mashina ham rad
etilardi.

SUBPROCESS YO'Q. `getmac`/`route` chaqiruvlari sekin mashinada
yuz millisekundlar oladi va frozen GUI'da qora konsol oynasini
chaqnatadi. Bu yerda faqat DLL chaqiruvi — mikrosoniyalar.

Modul HECH QANDAY QAROR QABUL QILMAYDI: u faqat adapterlarni
o'qiydi. "Qaysi MAC yuboriladi" degan tanlov `system_info.py`
da, "bu MAC ruxsat etilganmi" degan qaror esa serverda.
"""

from __future__ import annotations

import ctypes
import logging
import socket
import sys
from ctypes import POINTER, Structure, Union, byref, c_void_p
from ctypes.wintypes import BYTE, CHAR, DWORD, LPWSTR, ULONG, USHORT
from dataclasses import dataclass, replace
from typing import Optional

log = logging.getLogger(__name__)

# --- WinAPI konstantalari ---------------------------------------------
_AF_UNSPEC = 0
_AF_INET = 2

#: `GetAdaptersAddresses` bayroqlari. Bizga faqat adapter va uning
#: unicast manzili kerak — qolganini so'ramaslik javob hajmini va
#: chaqiruv vaqtini kamaytiradi.
_GAA_FLAG_SKIP_ANYCAST = 0x0002
_GAA_FLAG_SKIP_MULTICAST = 0x0004
_GAA_FLAG_SKIP_DNS_SERVER = 0x0008
_GAA_FLAGS = _GAA_FLAG_SKIP_ANYCAST | _GAA_FLAG_SKIP_MULTICAST | _GAA_FLAG_SKIP_DNS_SERVER

_ERROR_SUCCESS = 0
_ERROR_BUFFER_OVERFLOW = 111

#: `IF_OPER_STATUS`: 1 — `IfOperStatusUp`.
_IF_OPER_UP = 1

#: `IFTYPE` (IANA ifType). Faqat shu ikkitasi jismoniy tarmoq
#: interfeysi hisoblanadi; qolganlari (loopback, tunnel, PPP)
#: mashinani identifikatsiya qilish uchun yaramaydi.
_IF_TYPE_ETHERNET = 6
_IF_TYPE_WIFI = 71
_IF_TYPE_LOOPBACK = 24

#: MAC uzunligi: Ethernet/Wi-Fi da 6 bayt. Struktura maydoni 8
#: baytlik, ortiqchasi nol bilan to'ldiriladi.
_MAC_LENGTH = 6

#: `MIB_IPFORWARD_ROW2` uchun bufer hajmi. Haqiqiy struktura x64 da
#: ~104 bayt; zaxira bilan olinadi, chunki u Windows versiyalari
#: orasida kengayishi mumkin va biz undan hech nima o'qimaymiz.
_ROUTE_ROW_SIZE = 512

#: Marshrutni tanlash uchun manzil. Paket YUBORILMAYDI —
#: `GetBestInterface` faqat marshrut jadvaliga qaraydi, ya'ni
#: internet bo'lmasa ham to'g'ri javob qaytaradi.
_ROUTE_PROBE = "8.8.8.8"


class _SOCKADDR(Structure):
    _fields_ = [("sa_family", USHORT), ("sa_data", BYTE * 14)]


class _SOCKADDR_IN(Structure):
    _fields_ = [
        ("sin_family", USHORT),
        ("sin_port", USHORT),
        ("sin_addr", BYTE * 4),
        ("sin_zero", BYTE * 8),
    ]


class _SOCKADDR_IN6(Structure):
    _fields_ = [
        ("sin6_family", USHORT),
        ("sin6_port", USHORT),
        ("sin6_flowinfo", ULONG),
        ("sin6_addr", BYTE * 16),
        ("sin6_scope_id", ULONG),
    ]


class _SOCKADDR_INET(Union):
    """IPv4/IPv6 uchun umumiy manzil (28 bayt)."""

    _fields_ = [
        ("Ipv4", _SOCKADDR_IN),
        ("Ipv6", _SOCKADDR_IN6),
        ("si_family", USHORT),
    ]


class _SOCKET_ADDRESS(Structure):
    _fields_ = [("lpSockaddr", POINTER(_SOCKADDR)), ("iSockaddrLength", ctypes.c_int)]


class _IP_ADAPTER_UNICAST_ADDRESS(Structure):
    pass


# Strukturalar O'ZINI KO'RSATADI (`Next`), shuning uchun maydonlar
# klass yaratilgandan KEYIN belgilanadi.
_IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", ULONG),
    ("Flags", DWORD),
    ("Next", POINTER(_IP_ADAPTER_UNICAST_ADDRESS)),
    ("Address", _SOCKET_ADDRESS),
    # Qolgan maydonlar (PrefixOrigin, DadState, muddatlar) O'QILMAYDI
    # va shuning uchun e'lon ham qilinmaydi: buferni WinAPI ajratadi,
    # biz faqat `Next` bo'yicha yuramiz. Ortiqcha maydonni noto'g'ri
    # e'lon qilish esa butun ro'yxatni buzardi.
]


class _IP_ADAPTER_ADDRESSES(Structure):
    pass


_IP_ADAPTER_ADDRESSES._fields_ = [
    # Birinchi ikki maydon C tomonda `ULONGLONG` bilan bitta union
    # ichida (8 bayt). Ikkita 4 baytlik maydon aynan shu 8 baytni
    # qoplaydi va tekislanish ham mos keladi.
    ("Length", ULONG),
    ("IfIndex", DWORD),
    ("Next", POINTER(_IP_ADAPTER_ADDRESSES)),
    ("AdapterName", POINTER(CHAR)),
    ("FirstUnicastAddress", POINTER(_IP_ADAPTER_UNICAST_ADDRESS)),
    ("FirstAnycastAddress", c_void_p),
    ("FirstMulticastAddress", c_void_p),
    ("FirstDnsServerAddress", c_void_p),
    ("DnsSuffix", LPWSTR),
    ("Description", LPWSTR),
    ("FriendlyName", LPWSTR),
    ("PhysicalAddress", BYTE * 8),
    ("PhysicalAddressLength", ULONG),
    ("Flags", ULONG),
    ("Mtu", ULONG),
    ("IfType", DWORD),
    ("OperStatus", DWORD),
    # Bundan keyingi maydonlar (Ipv6IfIndex, ZoneIndices, FirstPrefix
    # va Vista+ qo'shimchalari) kerak emas — yuqoridagi izohga qarang.
]


@dataclass(frozen=True)
class Adapter:
    """Bitta tarmoq adapteri — o'qilgan holicha, xulosasiz."""

    if_index: int
    name: str
    description: str
    mac: str
    #: Serverga chiqishda ISHLATILADIGAN manzil (`ipv4_all` ning
    #: birinchisi). Bitta adapterda bir nechta manzil bo'lishi odatiy
    #: hol va ular teng EMAS - pastdagi `primary()` izohiga qarang.
    ipv4: str
    #: Adapterning barcha IPv4 manzillari, asosiysi birinchi.
    ipv4_all: tuple = ()
    if_type: int = 0
    oper_up: bool = False

    @property
    def is_physical(self) -> bool:
        """Ethernet yoki Wi-Fi. Loopback/tunnel/PPP — yo'q."""
        return self.if_type in (_IF_TYPE_ETHERNET, _IF_TYPE_WIFI)

    @property
    def is_locally_administered(self) -> bool:
        """
        MAC'ning ikkinchi biti — "lokal boshqariladigan" bayroq.

        Ishlab chiqaruvchi bergan (burned-in) manzilda u NOL.
        Virtual adapterlar (Hyper-V, VMware, VPN) va qo'lda
        o'zgartirilgan MAC'lar odatda birga teng. Bu KAFOLAT emas,
        faqat qo'shimcha signal: asosiy tanlov marshrut bo'yicha.
        """
        try:
            return bool(int(self.mac[:2], 16) & 0x02)
        except (ValueError, IndexError):
            return False


def is_supported() -> bool:
    """Bu platformada WinAPI yo'li ishlaydimi."""
    return sys.platform == "win32"


def _format_mac(raw: BYTE * 8, length: int) -> str:
    if length != _MAC_LENGTH:
        # 6 baytdan farqli manzil (masalan InfiniBand yoki tunnel)
        # inventarizatsiyaga yaramaydi: `Computer.mac_address`
        # maydoni AA:BB:CC:DD:EE:FF formatida.
        return ""
    return ":".join("{:02X}".format(raw[i] & 0xFF) for i in range(_MAC_LENGTH))


def _ipv4_addresses(entry: _IP_ADAPTER_ADDRESSES) -> list:
    """
    Adapterning BARCHA IPv4 unicast manzillari.

    Ilgari bu yerdan faqat BIRINCHI manzil olinardi va u xato edi:
    bitta adapterda bir nechta manzil bo'lishi odatiy hol (qo'lda
    qo'shilgan ikkinchi manzil, provayder bergan xizmat manzili) va
    ro'yxatdagi tartib "asosiysi" degani EMAS. Ishlab chiqish
    mashinasida aynan shu holat bor edi: `Ethernet` adapterida
    192.0.0.194 va 192.168.0.194, ro'yxatda birinchisi turadi,
    tarmoqqa esa ikkinchisi bilan chiqiladi.
    """
    found = []
    node = entry.FirstUnicastAddress
    while node:
        sockaddr = node.contents.Address.lpSockaddr
        if sockaddr and sockaddr.contents.sa_family == _AF_INET:
            # `sockaddr_in`: 2 bayt oila, 2 bayt port, 4 bayt manzil.
            # `sa_data` port'dan boshlanadi, ya'ni IP — 2-6 baytlar.
            found.append(socket.inet_ntoa(bytes(bytearray(sockaddr.contents.sa_data[2:6]))))
        node = node.contents.Next
    return found


def adapters() -> list:
    """
    Barcha adapterlar (filtrsiz, o'qilgan tartibda).

    Bufer IKKI MARTA so'raladi: birinchi chaqiruv kerakli hajmni
    aytadi. Hajmni oldindan taxmin qilish (masalan 15 KB) ko'p
    adapterli mashinada jimgina qisqargan ro'yxat berardi.
    """
    if not is_supported():
        return []

    iphlpapi = ctypes.WinDLL("iphlpapi.dll")
    size = ULONG(0)
    result = iphlpapi.GetAdaptersAddresses(
        _AF_INET, _GAA_FLAGS, None, None, byref(size)
    )
    if result != _ERROR_BUFFER_OVERFLOW:
        # Adapter umuman yo'q bo'lsa ham `ERROR_BUFFER_OVERFLOW`
        # qaytadi (bo'sh ro'yxat uchun ham joy kerak), shuning uchun
        # boshqa kod - haqiqiy xato.
        log.debug("GetAdaptersAddresses hajm so'rovi: %s", result)
        return []

    buffer = ctypes.create_string_buffer(size.value)
    result = iphlpapi.GetAdaptersAddresses(
        _AF_INET, _GAA_FLAGS, None, buffer, byref(size)
    )
    if result != _ERROR_SUCCESS:
        log.debug("GetAdaptersAddresses xatosi: %s", result)
        return []

    found = []
    entry = ctypes.cast(buffer, POINTER(_IP_ADAPTER_ADDRESSES))
    while entry:
        item = entry.contents
        addresses = _ipv4_addresses(item)
        found.append(
            Adapter(
                if_index=int(item.IfIndex),
                name=item.FriendlyName or "",
                description=item.Description or "",
                mac=_format_mac(item.PhysicalAddress, int(item.PhysicalAddressLength)),
                ipv4=addresses[0] if addresses else "",
                ipv4_all=tuple(addresses),
                if_type=int(item.IfType),
                oper_up=int(item.OperStatus) == _IF_OPER_UP,
            )
        )
        entry = item.Next
    return found


def best_source_ip(destination: str = _ROUTE_PROBE) -> str:
    """
    Berilgan manzilga chiqishda ISHLATILADIGAN manba IP.

    `GetBestRoute2` marshrut jadvaliga ham, manba manzilini tanlash
    qoidalariga ham (RFC 6724 + eng uzun prefiks) qaraydi — ya'ni bu
    OS'ning HAQIQIY javobi, taxmin emas.

    NIMA UCHUN ADAPTER RO'YXATIDAN TANLAB BO'LMAYDI: bitta adapterdagi
    ikkita manzilning metama'lumoti bir xil bo'lishi mumkin (ikkalasi
    ham `Manual`, `Preferred`, `SkipAsSource` emas). Ishlab chiqish
    mashinasida aynan shunday: 192.0.0.194 va 192.168.0.194 — bayroqlari
    bir xil, lekin tarmoqqa faqat ikkinchisi bilan chiqiladi. Farqni
    faqat marshrut biladi.
    """
    if not is_supported():
        return ""
    try:
        iphlpapi = ctypes.WinDLL("iphlpapi.dll")
        target = _SOCKADDR_INET()
        target.Ipv4.sin_family = _AF_INET
        for index, byte in enumerate(socket.inet_aton(destination)):
            target.Ipv4.sin_addr[index] = byte

        # `MIB_IPFORWARD_ROW2` O'QILMAYDI - bizga faqat manba manzili
        # kerak. Struktura katta (x64 da ~104 bayt) va uni to'liq
        # e'lon qilish bitta maydon uchun o'nlab qatorni talab
        # qilardi; buferning zaxira bilan olingani yetarli.
        route = ctypes.create_string_buffer(_ROUTE_ROW_SIZE)
        source = _SOCKADDR_INET()
        result = iphlpapi.GetBestRoute2(
            None, ULONG(0), None, byref(target), ULONG(0), route, byref(source)
        )
        if result != _ERROR_SUCCESS or source.si_family != _AF_INET:
            return ""
        return socket.inet_ntoa(bytes(bytearray(source.Ipv4.sin_addr)))
    except OSError:
        log.debug("GetBestRoute2 chaqirilmadi", exc_info=True)
        return ""


def _best_if_index(destination: str = _ROUTE_PROBE) -> Optional[int]:
    """
    Berilgan manzilga chiqadigan interfeys indeksi.

    `GetBestInterface` marshrut jadvalidan o'qiydi — bu OS'ning
    HAQIQIY qarori, taxmin emas. Aynan shu sabab u nom bo'yicha
    filtrlashdan ustun: virtual adapter qanday nomlansa ham,
    marshrut unga tushmasa, u tanlanmaydi.
    """
    if not is_supported():
        return None
    try:
        iphlpapi = ctypes.WinDLL("iphlpapi.dll")
        # `IPAddr` — tarmoq tartibidagi 32 bitli manzil.
        packed = socket.inet_aton(destination)
        address = ULONG(int.from_bytes(packed, "little"))
        index = DWORD(0)
        if iphlpapi.GetBestInterface(address, byref(index)) != _ERROR_SUCCESS:
            return None
        return int(index.value)
    except OSError:
        log.debug("GetBestInterface chaqirilmadi", exc_info=True)
        return None


def primary(destination: str = _ROUTE_PROBE) -> Optional[Adapter]:
    """
    Serverga chiqadigan adapter: MAC va IP BITTA manbadan.

    Uch bosqichli tanlov va tartib muhim:

        1. marshrut bo'yicha (`GetBestInterface`) — OS qarori;
        2. marshrut bermasa: ishlayotgan jismoniy adapterlar
           orasidan burned-in MAC'lisi (virtual adapterlar odatda
           lokal boshqariladigan manzil oladi);
        3. shunday adapter ham bo'lmasa: IPv4'i bor birinchi
           jismoniy adapter.

    Hech biri topilmasa `None` — chaqiruvchi zaxira usulga
    (psutil, OS buyrug'i) o'tadi.

    ADAPTER TOPILGACH IKKINCHI TANLOV BOR: uning MANZILI. Bitta
    adapterda bir nechta IPv4 bo'lishi odatiy hol va ro'yxatdagi
    tartib "asosiysi" degani emas — shuning uchun marshrut tanlagan
    manba manzili (`best_source_ip`) birinchi o'ringa suriladi.
    Usiz panelda mashinaning ikkinchi darajali manzili ko'rinardi
    va operator uni administratorga aytganda hech qayerda
    topilmasdi.
    """
    found = [item for item in adapters() if item.mac]
    if not found:
        return None

    source = best_source_ip(destination)
    index = _best_if_index(destination)
    if index is not None:
        for item in found:
            if item.if_index == index and item.is_physical:
                return _with_primary_ip(item, source)

    usable = [item for item in found if item.is_physical and item.oper_up]
    for item in usable:
        if item.ipv4 and not item.is_locally_administered:
            return _with_primary_ip(item, source)
    for item in usable:
        if item.ipv4:
            return _with_primary_ip(item, source)
    return _with_primary_ip(usable[0], source) if usable else None


def _with_primary_ip(adapter: Adapter, source: str) -> Adapter:
    """
    Marshrut tanlagan manzilni birinchi o'ringa qo'yadi.

    Manzil shu adapterga tegishli bo'lmasa (masalan marshrut boshqa
    interfeysdan ketadi) tartib O'ZGARMAYDI: begona manzilni
    adapterga yozib qo'yish yolg'on ma'lumot bo'lardi.
    """
    if not source or source not in adapter.ipv4_all:
        return adapter
    ordered = (source,) + tuple(ip for ip in adapter.ipv4_all if ip != source)
    return replace(adapter, ipv4=source, ipv4_all=ordered)


def all_ipv4() -> list:
    """
    Mashinaning barcha IPv4 manzillari: `[(adapter nomi, ip), ...]`.

    Diagnostika uchun: operator "IP nechta?" degan savolga javob
    bera olishi kerak. Loopback va APIPA (169.254.x.x) tashlanadi —
    birinchisi har mashinada bir xil, ikkinchisi esa "DHCP javob
    bermadi" degani va u manzil bilan hech qayerga ulanib
    bo'lmaydi.
    """
    result = []
    for adapter in adapters():
        if not adapter.is_physical or not adapter.oper_up:
            continue
        for ip in adapter.ipv4_all:
            if ip.startswith(("127.", "169.254.")):
                continue
            result.append((adapter.name or adapter.description, ip))
    return result
