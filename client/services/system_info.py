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
import uuid
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
def hardware_fingerprint(mac: Optional[str] = None) -> str:
    """
    Apparat izi: `muid:<Machine UUID>|mac:<MAC>`.

    Kredensial EMAS - backend uni anomaliya signali sifatida ishlatadi
    ("bitta apparat ostida bir nechta qurilma", "device_id boshqa
    mashinaga ko'chirilgan"). Shuning uchun u BARQAROR bo'lishi shart.

    MAC NIMA UCHUN QAYTDI. Arzon platalarda SMBIOS UUID bir partiyada
    bir xil bo'ladi, ya'ni faqat `muid:<UUID>` izi ikki BOSHQA
    mashinada bir xil chiqardi va ikkinchisi ro'yxatdan o'tishda
    birinchisining `device_id` sini olib qo'yardi. Mashina server
    uchun (UUID, MAC) JUFTLIGI - iz ham shu juftlik.

    `mac` - so'rovning o'zida yuborilayotgan MAC (handshake'dagi
    `machine["mac"]`): iz va `mac_address` maydoni BITTA adapterdan
    bo'lishi shart, aks holda server ularni bir mashina deb bilmaydi.
    Berilmasa `mac_address()` o'qiladi. MAC aniqlanmasa - eski
    `muid:<UUID>` shakli (server uni eski iz deb taniydi).

    Shakl server bilan AYNAN bir xil (katta harf, ikki nuqta -
    `devices.services.fingerprint_for`). `muid:` prefiksi ikki
    tomonlama shartnoma, o'zgartirmang. Eski izlardan o'tishni server
    taniydi (`devices.services.is_fingerprint_upgrade`).
    """
    uuid_value = machine_uuid()
    mac_value = _normalize_mac(mac if mac is not None else mac_address())
    if not mac_value:
        return "muid:{}".format(uuid_value)[:128]
    return "muid:{}|mac:{}".format(uuid_value, mac_value)[:128]


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
    Mashina identifikatori (Machine UUID) + MAC va IP - BITTA adapterdan.

    `machine_uuid` - server uchun ASOSIY identifikator
    (`Computer.machine_uuid`); MAC va IP - ikkilamchi va ekrandagi
    ma'lumot (sarlavhadagi kataklar faqat MAC/IP ni ko'rsatadi).

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
            "machine_uuid": machine_uuid(),
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
            "machine_uuid": machine_uuid(),
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
    # MAC bir marta o'qiladi: `mac_address` maydoni va iz bitta
    # qiymatdan bo'lishi kerak (server ikkalasini solishtiradi).
    mac = mac_address()
    return {
        # Server kompyuterni (UUID, MAC) juftligi bo'yicha qidiradi.
        "machine_uuid": machine_uuid(),
        "mac_address": mac,
        "ip_address": local_ip(),
        "public_ip": public_ip(public_ip_timeout),
        "hardware_fingerprint": hardware_fingerprint(mac),
        "info_pc": info_pc(),
    }


# ---------------------------------------------------------------------
# Apparat UUID (SMBIOS) - har qanday Windows'da, har qanday hisobda
# ---------------------------------------------------------------------
_uuid_lock = threading.Lock()
_uuid_cache: Optional[tuple] = None

#: `GetSystemFirmwareTable` provayderi - 'RSMB' (xom SMBIOS jadvali).
_RSMB = 0x52534D42

_UUID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")

#: Ishlab chiqaruvchi to'ldirmagan "UUID"lar. Ular ko'p mashinada BIR XIL
#: bo'ladi (arzon ona platalar, "To Be Filled By O.E.M.") va mashinani
#: ajratmaydi - bunday qiymat yaroqsiz deb keyingi manbaga o'tiladi.
_PLACEHOLDER_UUIDS = frozenset({
    "00000000-0000-0000-0000-000000000000",
    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    "03000200-0400-0500-0006-000700080009",
    "00020003-0004-0005-0006-000700080009",
    "12345678-1234-5678-90AB-CDDEEFAABBCC",
    "01234567-89AB-CDEF-0123-456789ABCDEF",
})

#: Zaxira UUID (apparat UUID'i yo'q/yaroqsiz) uchun nom maydoni: shu
#: dastur yasagan qiymat boshqa tizimlarnikiga to'qnashmasligi uchun.
_DERIVED_NAMESPACE = uuid.UUID("6f1d2c1e-5b8a-4c3e-9f47-0a1b2c3d4e5f")


def normalize_machine_uuid(value) -> str:
    """
    Qiymatni kanonik shaklga keltiradi va TEKSHIRADI.

    Qaytadi: `XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX` (katta harf) yoki
    bo'sh satr (yaroqsiz). Qavslar (`{...}`, registrda shunday) va
    bo'shliqlar olib tashlanadi.

    Yaroqsiz: format buzilgan, ma'lum "to'ldirilmagan" qiymat yoki
    past entropiya (3 tadan kam turli belgi - `11111111-...` kabi).
    """
    text = str(value or "").strip().strip("{}").strip().upper()
    if not _UUID_RE.match(text):
        return ""
    if text in _PLACEHOLDER_UUIDS:
        return ""
    if len(set(text.replace("-", ""))) < 3:
        return ""
    return text


def machine_uuid() -> str:
    """
    Ona platadagi SMBIOS UUID - `wmic csproduct get uuid` bilan AYNAN bir
    xil satr ("4C4C4544-0038-4A10-805A-C7C04F4XXXXX"). HECH QACHON BO'SH
    QAYTMAYDI va har doim `normalize_machine_uuid` dan o'tgan.

    Nima uchun aynan SMBIOS: u APPARATNIKI. Windows'ning `MachineGuid`
    o'rnatishga tegishli va mashina obrazi ko'chirilganda (imtihon
    markazlarida odatiy) o'nlab mashinada BIR XIL bo'lib qoladi.

    MANBALAR ZANJIRI - birinchi YAROQLI qiymat olinadi:

      1. `smbios`   GetSystemFirmwareTable('RSMB') - ~1 ms, oddiy
                    foydalanuvchi, Windows XP SP2+ / Server, xizmat
                    (session 0) ham;
      2. `registry` HKLM\\SYSTEM\\HardwareConfig\\LastConfig - Windows
                    ishga tushishda SMBIOS UUID'ini o'zi yozadi; API
                    bloklangan (ba'zi VDI/sandbox) holat uchun;
      3. `cim`      PowerShell Get-CimInstance (WMI) - sekin (~1 s),
                    faqat oldingilari ishlamasa;
      4. `wmic`     eski tizimlar (Windows 11 24H2+ da wmic YO'Q);
      5. `derived`  apparat UUID'i umuman yo'q yoki "to'ldirilmagan"
                    (arzon ona plata, ba'zi virtual mashinalar):
                    UUIDv5(asosiy MAC) -> (MachineGuid) -> (kompyuter
                    nomi). Barqaror (har ishga tushishda bir xil), lekin
                    apparat UUID'i EMAS - log'da WARNING bilan aytiladi.

    Natija jarayon umri davomida keshlanadi: apparat o'zgarmaydi, WMI
    esa har so'rovda chaqirilsa platformaning har `device_info` si
    soniyalab kutardi.
    """
    return _resolve_machine_uuid()[0]


def machine_uuid_source() -> str:
    """Qiymat qaysi manbadan olingani (diagnostika uchun)."""
    return _resolve_machine_uuid()[1]


def _resolve_machine_uuid() -> tuple:
    global _uuid_cache
    with _uuid_lock:
        if _uuid_cache is not None:
            return _uuid_cache
        for source, reader in (
            ("smbios", _uuid_from_smbios),
            ("registry", _uuid_from_registry),
            ("cim", _uuid_from_cim),
            ("wmic", _uuid_from_wmic),
        ):
            try:
                raw = reader()
            except Exception:
                log.debug("Machine UUID (%s) o'qilmadi", source, exc_info=True)
                continue
            value = normalize_machine_uuid(raw)
            if value:
                log.info("Machine UUID: %s (manba: %s)", value, source)
                _uuid_cache = (value, source)
                return _uuid_cache
            if raw:
                log.warning("Machine UUID (%s) yaroqsiz: %r - keyingi manba", source, raw)

        value, basis = _derived_uuid()
        log.warning(
            "Apparat UUID'i topilmadi yoki yaroqsiz - barqaror zaxira UUID "
            "ishlatiladi: %s (asos: %s)", value, basis,
        )
        _uuid_cache = (value, f"derived:{basis}")
        return _uuid_cache


def _uuid_from_smbios() -> str:
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_table = kernel32.GetSystemFirmwareTable
    # `argtypes` SHART (`CLAUDE.md`: ctypes tuzog'i) - bufer ko'rsatkichi
    # 64-bit va `int` sifatida uzatilsa kesilardi.
    get_table.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    get_table.restype = wintypes.UINT

    size = get_table(_RSMB, 0, None, 0)
    if not size:
        return ""
    buffer = (ctypes.c_ubyte * size)()
    written = get_table(_RSMB, 0, buffer, size)
    if not written or written > size:
        return ""
    return parse_smbios_uuid(bytes(buffer)[:written])


def _uuid_from_registry() -> str:
    if sys.platform != "win32":
        return ""
    import winreg

    # `KEY_WOW64_64KEY`: 32-bit Python ham 64-bit registr ko'rinishini o'qisin.
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\HardwareConfig", 0, access) as key:
        value, _kind = winreg.QueryValueEx(key, "LastConfig")
    return str(value or "")


def _uuid_from_cim() -> str:
    if sys.platform != "win32":
        return ""
    output = _run(
        [
            "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command", "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID",
        ],
        timeout=15.0,
    )
    return output.strip().splitlines()[-1].strip() if output.strip() else ""


def _uuid_from_wmic() -> str:
    if sys.platform != "win32":
        return ""
    output = _run(["wmic", "csproduct", "get", "uuid"], timeout=10.0)
    for line in output.splitlines():
        line = line.strip()
        if line and line.upper() != "UUID":
            return line
    return ""


def _derived_uuid() -> tuple:
    """Oxirgi zaxira: barqaror, mashinaga xos UUIDv5 (hech qachon bo'sh emas)."""
    # `machine_identity()` EMAS: u `machine_uuid()` ni chaqiradi, bu esa
    # `_uuid_lock` ichida - qulf qayta kirishli emas va jarayon osilib
    # qolardi. MAC to'g'ridan-to'g'ri o'qiladi (o'sha manbalar).
    try:
        mac = mac_address()
    except Exception:
        mac = ""
    if mac:
        return str(uuid.uuid5(_DERIVED_NAMESPACE, "mac:" + mac)).upper(), "mac"
    if sys.platform == "win32":
        try:
            import winreg

            access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access
            ) as key:
                guid, _kind = winreg.QueryValueEx(key, "MachineGuid")
            if guid:
                return str(uuid.uuid5(_DERIVED_NAMESPACE, "guid:" + str(guid))).upper(), "machine_guid"
        except OSError:
            pass
    name = platform.node() or socket.gethostname() or "unknown"
    return str(uuid.uuid5(_DERIVED_NAMESPACE, "host:" + name.lower())).upper(), "hostname"


def parse_smbios_uuid(raw: bytes) -> str:
    """
    `RawSMBIOSData` dan 1-tur strukturaning UUID'i.

    Sof funksiya - testda sintetik jadval bilan tekshiriladi.

    Sarlavha 8 bayt: chaqiruv usuli, major, minor, DMI reviziyasi,
    jadval uzunligi (4 bayt). Har struktura: tur, formatlangan qism
    uzunligi, dastak, keyin satrlar bo'limi (ikki NUL bilan tugaydi).
    UUID 1-turning 8-baytidan 16 bayt.

    BAYT TARTIBI VERSIYAGA BOG'LIQ: SMBIOS 2.6+ da birinchi uchta maydon
    little-endian (`bytes_le`), undan eskisida big-endian. `wmic` ham
    aynan shu qoida bilan chiqaradi - aks holda ikki vosita bitta
    mashinaga ikki xil UUID berardi.
    """
    import uuid

    if len(raw) < 8:
        return ""
    major, minor = raw[1], raw[2]
    length = int.from_bytes(raw[4:8], "little")
    table = raw[8:8 + length]

    offset = 0
    while offset + 4 <= len(table):
        kind, header_len = table[offset], table[offset + 1]
        if header_len < 4:
            break
        if kind == 1 and header_len >= 0x19 and offset + 24 <= len(table):
            value = table[offset + 8:offset + 24]
            if value in (b"\x00" * 16, b"\xff" * 16):
                return ""
            modern = (major, minor) >= (2, 6)
            parsed = uuid.UUID(bytes_le=value) if modern else uuid.UUID(bytes=value)
            return str(parsed).upper()
        if kind == 127:  # jadval oxiri
            break
        # Satrlar bo'limini o'tkazib yuborish: ikki ketma-ket NUL.
        cursor = offset + header_len
        while cursor + 1 < len(table) and not (table[cursor] == 0 and table[cursor + 1] == 0):
            cursor += 1
        offset = cursor + 2
    return ""
