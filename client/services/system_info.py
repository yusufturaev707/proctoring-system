"""
Mashina haqidagi ma'lumot: LAN IP, MAC, public IP, apparat izi.

Uchta manzil uchta boshqa savolga javob beradi va ular ARALASHTIRILMAYDI:

    LAN IP     - mashina bino ichida qaysi manzilda (`Computer.ip_address`)
    MAC        - mashinaning o'zi kim (global unikal, asosiy belgi)
    public IP  - bino internetga qaysi manzil bilan chiqadi

Har biri uchun gibrid strategiya: eng ISHONCHLI usul birinchi,
ishlamasa keyingisi. Sabab - imtihon markazlaridagi mashinalar bir
xil emas: virtual adapterlar (WSL, VMware, Hyper-V), o'chirilgan
WMI, proxy ortidagi tarmoq, tizim tili har xil.

Windows'da birinchi usul - WinAPI (`winapi_net.py`): u marshrut
jadvalidan "serverga qaysi adapter orqali chiqiladi" degan javobni
oladi va MAC bilan IP ni AYNAN o'sha adapterdan beradi. Bu muhim,
chunki MAC server tomonda mashinani identifikatsiya qiladi
(`Computer.mac_address`) - Hyper-V adapterining MAC'i yuborilsa,
to'g'ri ro'yxatga olingan mashina ham "ro'yxatda yo'q" bo'lib
chiqardi.

QOIDA: bu moduldagi hech bir funksiya UI thread'ni uzoq bloklamaydi.
Public IP tashqi so'rov talab qiladi, shuning uchun u FON rejimida
oldindan olinadi va keshlanadi (`PublicIpResolver`).
"""

from __future__ import annotations

import logging
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

_IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")

#: Windows'da konsol oynasi ochilmasligi uchun. Frozen GUI dasturda
#: `subprocess` har chaqiruvda qora oyna chaqnatadi - operator buni
#: "dastur nimadir qilyapti" deb qabul qiladi.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

#: Virtual adapterlar. Nomga tayanish ideal emas (tizim tili har xil),
#: shuning uchun u FAQAT zaxira yo'lda ishlatiladi: asosiy usul -
#: marshrutga qarab tanlash.
_VIRTUAL_HINTS = (
    "loopback", "vethernet", "wsl", "docker", "vmware", "virtualbox",
    "hyper-v", "vpn", "tap", "tun", "bluetooth",
)


def _run(command: list, timeout: float = 5.0) -> str:
    """Buyruqni ishga tushiradi va stdout ni qaytaradi (xato bo'lsa - bo'sh)."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Buyruq bajarilmadi %s: %s", command[0], exc)
        return ""
    # Windows konsoli cp866/cp1251 bo'lishi mumkin - `errors="replace"`
    # bilan dekodlaymiz, chunki bizga faqat raqamlar kerak.
    return result.stdout.decode("utf-8", errors="replace") or result.stdout.decode(
        "cp866", errors="replace"
    )


def _winapi_primary():
    """
    Serverga chiqadigan adapter yoki `None`.

    Xato YUTILADI: WinAPI yo'li ishlamasa (Windows emas, DLL
    o'zgargan, huquq yetmagan) modul zaxira usullarga tushishi
    kerak - manzil aniqlanmasligi dasturni to'xtatmaydi.
    """
    try:
        from services import winapi_net

        return winapi_net.primary()
    except Exception:
        log.debug("WinAPI adapteri o'qilmadi", exc_info=True)
        return None


# ---------------------------------------------------------------------
# LAN IP
# ---------------------------------------------------------------------
def _ip_via_winapi() -> str:
    """Marshrut tanlagan adapterning IPv4 manzili (faqat Windows)."""
    adapter = _winapi_primary()
    return adapter.ipv4 if adapter is not None else ""


def _ip_via_socket() -> str:
    """
    UDP socket orqali OS marshrutidan olish - eng tez va ishonchli usul.

    Paket YUBORILMAYDI: `connect()` UDP uchun faqat marshrutni tanlaydi,
    ya'ni internet bo'lmasa ham ishlaydi va hech qanday kechikish yo'q.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 1))
        ip = sock.getsockname()[0]
        return ip if ip and not ip.startswith("127.") else ""
    except OSError:
        return ""
    finally:
        sock.close()


def _interfaces() -> dict:
    try:
        import psutil

        return psutil.net_if_addrs()
    except Exception:
        log.debug("psutil interfeyslarini o'qib bo'lmadi", exc_info=True)
        return {}


def _ip_via_psutil() -> str:
    """Virtual bo'lmagan interfeysdan birinchi haqiqiy IPv4."""
    for name, addresses in _interfaces().items():
        if any(hint in name.lower() for hint in _VIRTUAL_HINTS):
            continue
        for item in addresses:
            if item.family != socket.AF_INET:
                continue
            ip = item.address or ""
            # 169.254.x.x - APIPA, ya'ni DHCP javob bermagan. Bunday
            # manzil bilan hech qayerga ulanib bo'lmaydi.
            if ip and not ip.startswith(("127.", "169.254.")):
                return ip
    return ""


def _ip_via_os_command() -> str:
    """OS buyruqlari - oxirgi chora (psutil ham ishlamaganda)."""
    if sys.platform == "win32":
        text = _run(["route", "print", "0.0.0.0"])
        # "0.0.0.0  0.0.0.0  <gateway>  <interfeys IP>  <metrika>"
        match = re.search(
            r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)", text
        )
        return match.group(2) if match else ""

    if sys.platform.startswith("linux"):
        match = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", _run(["ip", "route", "get", "8.8.8.8"]))
        return match.group(1) if match else ""

    if sys.platform == "darwin":
        for iface in ("en0", "en1"):
            ip = _run(["ipconfig", "getifaddr", iface]).strip()
            if _IPV4_RE.match(ip):
                return ip
    return ""


def local_ip() -> str:
    """Mashinaning LAN manzili. Topilmasa `0.0.0.0`."""
    for method in (_ip_via_winapi, _ip_via_socket, _ip_via_psutil, _ip_via_os_command):
        try:
            ip = method()
        except Exception:
            log.debug("%s xatosi", method.__name__, exc_info=True)
            continue
        if ip:
            return ip
    log.warning("LAN IP aniqlanmadi")
    return "0.0.0.0"


# ---------------------------------------------------------------------
# MAC
# ---------------------------------------------------------------------
def _normalize_mac(value: str) -> str:
    mac = str(value or "").replace("-", ":").upper().strip()
    if not _MAC_RE.match(mac):
        return ""
    if mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
        return ""
    return mac


def _mac_via_winapi() -> str:
    """Marshrut tanlagan adapterning MAC'i (faqat Windows)."""
    adapter = _winapi_primary()
    return _normalize_mac(adapter.mac) if adapter is not None else ""


def _mac_of_active_interface() -> str:
    """
    Serverga chiqadigan interfeysning MAC'i.

    Interfeys NOMIGA tayanmaymiz - u tizim tilida bo'ladi va virtual
    adapterlarni nom bo'yicha ajratish ishonchsiz. O'rniga: qaysi
    interfeysda bizning LAN IP'imiz bo'lsa, o'shaniki.
    """
    import psutil

    target = local_ip()
    interfaces = _interfaces()

    if target and target != "0.0.0.0":
        for addresses in interfaces.values():
            if not any(
                item.family == socket.AF_INET and item.address == target
                for item in addresses
            ):
                continue
            for item in addresses:
                if item.family == psutil.AF_LINK:
                    mac = _normalize_mac(item.address)
                    if mac:
                        return mac

    # Zaxira: globally unique (burned-in) manzil. Ikkinchi bit 0 bo'lsa -
    # manzilni ishlab chiqaruvchi bergan, ya'ni virtual adapter emas.
    for name, addresses in interfaces.items():
        if any(hint in name.lower() for hint in _VIRTUAL_HINTS):
            continue
        for item in addresses:
            if item.family == psutil.AF_LINK:
                mac = _normalize_mac(item.address)
                if mac and not int(mac[:2], 16) & 0x02:
                    return mac
    return ""


def _mac_via_os_command() -> str:
    if sys.platform == "win32":
        # `getmac` - PowerShell'dan tez (PS ishga tushishi ~1 s oladi).
        text = _run(["getmac", "/fo", "csv", "/nh"])
        for line in text.splitlines():
            mac = _normalize_mac(line.split(",")[0].strip('" '))
            if mac:
                return mac
        return ""

    if sys.platform.startswith("linux"):
        device = re.search(r"dev\s+(\S+)", _run(["ip", "route", "get", "8.8.8.8"]))
        if device:
            match = re.search(
                r"link/ether\s+([\da-fA-F:]{17})", _run(["ip", "link", "show", device.group(1)])
            )
            if match:
                return _normalize_mac(match.group(1))
        return ""

    if sys.platform == "darwin":
        for iface in ("en0", "en1"):
            match = re.search(r"ether\s+([\da-fA-F:]{17})", _run(["ifconfig", iface]))
            if match:
                return _normalize_mac(match.group(1))
    return ""


def mac_address() -> str:
    """
    Mashinaning barqaror MAC manzili.

    `uuid.getnode()` ATAYLAB ishlatilmaydi: haqiqiy manzilni topa olmasa,
    u TASODIFIY qiymat qaytaradi (RFC 4122, multicast biti qo'yilgan) va
    u har ishga tushishda boshqacha bo'ladi - qurilma har safar yangi
    mashina kabi ko'rinardi.
    """
    for method in (_mac_via_winapi, _mac_of_active_interface, _mac_via_os_command):
        try:
            mac = method()
        except Exception:
            log.debug("%s xatosi", method.__name__, exc_info=True)
            continue
        if mac:
            return mac

    import uuid

    node = uuid.getnode()
    mac = ":".join("{:02X}".format((node >> shift) & 0xFF) for shift in range(40, -8, -8))
    log.warning("MAC interfeyslardan olinmadi - uuid.getnode() ishlatildi: %s", mac)
    return mac


# ---------------------------------------------------------------------
# Public IP
# ---------------------------------------------------------------------
#: (url, JSON kaliti yoki None = oddiy matn)
_PUBLIC_IP_PROVIDERS = (
    ("https://api.ipify.org/?format=json", "ip"),
    ("https://ifconfig.me/ip", None),
    ("https://icanhazip.com", None),
    ("http://api.ipify.org/?format=json", "ip"),
)


class PublicIpResolver:
    """
    Public IP ni fon rejimida oladi va keshlaydi.

    Nega kesh va fon: bu YAGONA tashqi tarmoq so'rovi. Login oqimida
    sinxron chaqirilsa, internet sekin bo'lganda operator har kirishda
    bir necha soniya kutardi - imtihon kunida bu yuzlab yo'qotilgan
    soniya. Shuning uchun qiymat dastur ishga tushganda oldindan
    olinadi; tayyor bo'lmasa, so'rov bo'sh qiymat bilan ketaveradi
    (server buni "noma'lum" deb qabul qiladi).
    """

    #: Kesh muddati. Bino kanali kun davomida o'zgarishi mumkin
    #: (rezerv kanalga o'tish), lekin har daqiqada emas.
    TTL_SECONDS = 15 * 60

    def __init__(self) -> None:
        self._value = ""
        self._fetched_at = 0.0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    @property
    def cached(self) -> str:
        """Bloklamaydi: kesh bo'sh yoki eskirgan bo'lsa '' qaytaradi."""
        if self._value and (time.time() - self._fetched_at) < self.TTL_SECONDS:
            return self._value
        return ""

    def prefetch(self) -> None:
        """Fon thread'ida yangilaydi (dastur ishga tushganda chaqiriladi)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self.cached:
                return
            self._thread = threading.Thread(
                target=self._refresh, name="public-ip", daemon=True
            )
            self._thread.start()

    def resolve(self, timeout: float = 0.0) -> str:
        """
        Keshdagi qiymat. `timeout` berilsa - shuncha kutadi.

        Login oqimi `timeout=0` bilan chaqiradi: kutish yo'q.
        """
        if self.cached:
            return self.cached
        self.prefetch()
        if timeout > 0 and self._thread is not None:
            self._thread.join(timeout)
        return self.cached

    def _refresh(self) -> None:
        value = self._fetch()
        if value:
            self._value = value
            self._fetched_at = time.time()
            log.info("Public IP: %s", value)
        else:
            log.info("Public IP aniqlanmadi (internet yo'q yoki provayderlar javob bermadi)")

    @staticmethod
    def _fetch() -> str:
        import httpx

        for url, json_key in _PUBLIC_IP_PROVIDERS:
            # SSL: avval odatdagi tekshiruv. Imtihon markazlarida
            # antivirus/proxy o'z sertifikatini kiritib qo'ygan bo'lishi
            # mumkin - u holda tekshiruvsiz urinamiz. Bu xavfsiz:
            # javobdan faqat IPv4 satri olinadi, hech qanday sir
            # uzatilmaydi.
            for verify in (True, False):
                try:
                    response = httpx.get(
                        url,
                        timeout=4.0,
                        verify=verify,
                        headers={"User-Agent": "ProctoringClient/1.0"},
                        follow_redirects=True,
                    )
                except Exception:
                    continue
                if response.status_code != 200:
                    continue
                try:
                    raw = response.json().get(json_key, "") if json_key else response.text
                except Exception:
                    continue
                ip = str(raw or "").strip()
                if _IPV4_RE.match(ip):
                    return ip
                break  # bu provayder javob berdi, lekin yaroqsiz - keyingisiga
        return ""


#: Yagona nusxa - kesh butun dastur bo'ylab bitta bo'lishi kerak.
public_ip_resolver = PublicIpResolver()


def public_ip(timeout: float = 0.0) -> str:
    return public_ip_resolver.resolve(timeout)


# ---------------------------------------------------------------------
# Umumiy
# ---------------------------------------------------------------------
def hardware_fingerprint() -> str:
    """
    Apparat izi: MAC + host nomi + platforma.

    Kredensial EMAS - backend uni anomaliya signali sifatida ishlatadi
    ("bitta apparat ostida bir nechta qurilma", "device_id boshqa
    mashinaga ko'chirilgan"). Shuning uchun u BARQAROR bo'lishi shart.
    """
    return "{}|{}|{}|{}".format(
        mac_address(), socket.gethostname(), platform.system(), platform.machine()
    )[:128]


def info_pc() -> dict:
    """Panelda ko'rsatiladigan qo'shimcha ma'lumot (`Computer.info_pc`)."""
    data = {
        "os": platform.platform(),
        "hostname": socket.gethostname(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    try:
        import psutil

        memory = psutil.virtual_memory()
        data.update(
            {
                "cpu_count": psutil.cpu_count(),
                "memory_total_gb": round(memory.total / (1024 ** 3), 1),
            }
        )
    except Exception:
        log.debug("psutil tizim ma'lumotini bermadi", exc_info=True)
    return data


#: `machine_identity()` keshi. MAC mashina ishlab turganda
#: o'zgarmaydi, IP esa DHCP ijarasi yangilanganda o'zgarishi
#: mumkin - shuning uchun kesh bor, lekin uni MAJBURAN yangilash
#: ham mumkin ("Yangilash" tugmasi aynan shuni qiladi).
_identity_lock = threading.Lock()
_identity_cache: dict = {}


def machine_identity(refresh: bool = False) -> dict:
    """
    MAC va IP - BITTA adapterdan, bitta chaqiruvda.

    `mac_address()` va `local_ip()` ni alohida chaqirish MUMKIN,
    lekin bu yerda ular ATAYLAB birga olinadi: server ikkalasini
    bitta mashinaning tavsifi deb qabul qiladi
    (`Computer.mac_address` + `Computer.ip_address`), turli
    adapterdan kelgan juftlik esa mavjud bo'lmagan mashinani
    tasvirlardi.

    `source` - qiymat qayerdan kelgani (`winapi` / `fallback`).
    U diagnostika uchun: MAC bo'yicha tekshiruv rad etganda
    birinchi savol "qaysi adapter o'qilgan?" bo'ladi.

    BLOKLAYDI: zaxira yo'lda OS buyrug'i ishga tushishi mumkin
    (~100-500 ms). Fon thread'idan chaqiring.
    """
    with _identity_lock:
        if _identity_cache and not refresh:
            return dict(_identity_cache)

    adapter = _winapi_primary()
    if adapter is not None and adapter.mac:
        primary_ip = adapter.ipv4 or local_ip()
        identity = {
            "mac": _normalize_mac(adapter.mac),
            "ip": primary_ip,
            "source": "winapi",
            "adapter": adapter.name or adapter.description,
            "ips": _all_addresses(primary_ip),
        }
    else:
        # Zaxira: ikkala qiymat alohida yo'l bilan olinadi. Ular
        # bir adapterdan bo'lishi KAFOLATLANMAYDI va buni chaqiruvchi
        # `source` orqali biladi.
        primary_ip = local_ip()
        identity = {
            "mac": mac_address(),
            "ip": primary_ip,
            "source": "fallback",
            "adapter": "",
            "ips": _all_addresses(primary_ip),
        }

    with _identity_lock:
        _identity_cache.clear()
        _identity_cache.update(identity)
    # Barcha manzillar ham LOG'GA tushadi: "panelda boshqa IP
    # ko'rinyapti" degan savolga javob shu qatordan boshlanadi.
    log.info(
        "Mashina: MAC %s / IP %s (%s%s)%s",
        identity["mac"] or "-",
        identity["ip"] or "-",
        identity["source"],
        ", " + identity["adapter"] if identity.get("adapter") else "",
        " | barcha manzillar: {}".format(
            ", ".join("{} ({})".format(ip, name) for name, ip in identity["ips"])
        )
        if len(identity["ips"]) > 1
        else "",
    )
    return dict(identity)


def _all_addresses(primary_ip: str = "") -> list:
    """
    Mashinaning barcha IPv4 manzillari: `[(adapter nomi, ip), ...]`.

    Asosiy manzil BIRINCHI turadi - ro'yxat operatorga ko'rsatiladi
    va u yerda tartib ma'noli bo'lishi kerak.

    Windows'da manba `winapi_net`, boshqa joyda psutil. Ikkalasi
    ham bo'lmasa kamida asosiy manzil qaytadi: bo'sh ro'yxat
    "manzil yo'q" degan noto'g'ri xulosa berardi.
    """
    entries: list = []
    try:
        from services import winapi_net

        entries = winapi_net.all_ipv4()
    except Exception:
        log.debug("WinAPI manzillari o'qilmadi", exc_info=True)

    if not entries:
        for name, addresses in _interfaces().items():
            if any(hint in name.lower() for hint in _VIRTUAL_HINTS):
                continue
            for item in addresses:
                if item.family != socket.AF_INET:
                    continue
                ip = item.address or ""
                if ip and not ip.startswith(("127.", "169.254.")):
                    entries.append((name, ip))

    if not entries and primary_ip:
        entries = [("", primary_ip)]

    # Asosiy manzil boshiga: `sorted` barqaror, ya'ni qolganlarning
    # tartibi o'zgarmaydi.
    if primary_ip:
        entries.sort(key=lambda item: item[1] != primary_ip)
    return entries


def snapshot(public_ip_timeout: float = 0.0) -> dict:
    """Ro'yxatdan o'tish va handshake uchun to'liq to'plam."""
    return {
        "mac_address": mac_address(),
        "ip_address": local_ip(),
        "public_ip": public_ip(public_ip_timeout),
        "hardware_fingerprint": hardware_fingerprint(),
        "info_pc": info_pc(),
    }
