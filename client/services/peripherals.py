"""
Qo'shimcha qurilmalar: fleshka, tashqi disk, telefon, naushnik, modem...

Imtihon boshidan yakunigacha nima ULANDI va nima UZILDI - `DeviceWatcher`
shu moduldan so'raydi va hodisa qiladi (`peripheral_connected` /
`peripheral_removed`). Bu modul hech narsani TO'SMAYDI.

UCH MANBA, chunki bittasi hammasini ko'rmaydi:

  QURILMALAR (SetupAPI) - USB orqali ulangan har bir FIZIK qurilma.
    Bitta fleshka Windows'da 4-5 ta tugun (USB, USBSTOR disk, tom, WPD)
    beradi; ularni bitta qurilmaga `ContainerId` birlashtiradi - bitta
    fizik qurilmaning barcha tugunlarida u bir xil. Kompyuterning
    ICHKI qurilmalari (noutbuk kamerasi, touchpad, ichki Bluetooth)
    "kompyuter" konteynerida (`ROOT_CONTAINER`) - ular tashlanadi.
    Faqat USB/SD shinasidagi konteyner olinadi (`_WIRED_ENUMERATORS`):
    tarmoqdagi printer yoki televizor (SWD) yoqilsa hodisa bo'lmasin.

  DISKLAR (`GetLogicalDrives`) - disk harfi. Ichki kartaridagi SD karta
    yangi qurilma bermaydi (o'quvchi ichki), lekin yangi tom beradi.
    Kalitda tom seriya raqami: bir fleshka tez boshqasiga almashsa ham
    ko'rinadi.

  AUDIO (Core Audio) - FAOL audio qurilmalar. 3.5 mm jakli naushnik
    yangi qurilma bermaydi - mavjud qurilmaning holati o'zgaradi
    (drayver jakni sezsa). Bluetooth naushnik ham shu yerda: juftlangan
    BT qurilmaning tugunlari ulanmagan paytda ham "bor", ya'ni SetupAPI
    ulanish lahzasini ko'rmaydi - audio qurilma esa faqat ulanganda
    FAOL. Shu sababli faqat BT dagi konteynerlar qurilmalar manbaidan
    tashlanadi (ular USB shinada emas).

ANIQLANMAYDI (va bu cheklov kodda emas, fizikada): telefonga ulangan
mikronaushnik, cho'ntakdagi telefon, faqat zaryad kabeli - kompyuter
bilan aloqasi yo'q. Bular kamera va proktor ishi.

Sof qism (`group_devices`, `PeripheralTracker`) Windows'siz testlanadi.
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
from collections import defaultdict
from ctypes import POINTER, byref, c_void_p
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

#: "Kompyuterning o'zi" konteyneri - ichki qurilmalar.
ROOT_CONTAINER = "{00000000-0000-0000-ffff-ffffffffffff}"

#: Turlar va jiddiylik (hodisa `severity`). Server ballni faqat 2 dan
#: qo'shadi (`ingest._PERIPHERAL_RISK_MIN_SEVERITY`).
KIND_SEVERITY = {
    "storage": 3,    # fleshka, tashqi disk, SD karta, tarmoq diski
    "phone": 3,      # MTP/ADB telefon, planshet
    "network": 2,    # USB modem, Wi-Fi adapter, telefon orqali internet
    # Kamera audiodan OLDIN: veb-kameraning ichida mikrofon bor (o'lchandi:
    # Logi C270 konteynerida Camera + AudioEndpoint) - u "naushnik" emas.
    "camera": 2,     # qo'shimcha kamera
    "audio": 2,      # naushnik, garnitura
    "bluetooth": 2,  # Bluetooth adapter (dongle)
    "input": 1,      # sichqoncha, klaviatura, boshqa HID
    "other": 1,      # USB hub, kartaridar, printer...
}
#: Bir konteynerda bir necha tur bo'lsa - birinchisi (fleshkada WPD
#: tugun ham bor, lekin u "telefon" emas).
_KIND_PRIORITY = tuple(KIND_SEVERITY)

#: Imtihon BOSHIDA ulangani hodisa bo'lmaydigan turlar: stol
#: kompyuterida USB sichqoncha/klaviatura va imtihon kamerasining
#: o'zi - odatiy; Bluetooth naushnik baribir audio manbada ko'rinadi.
_QUIET_AT_START = frozenset({"input", "camera", "bluetooth"})

_CLASS_KIND = {
    "diskdrive": "storage", "cdrom": "storage", "volume": "storage",
    "floppydisk": "storage", "tapedrive": "storage",
    "wpd": "phone", "androidusbdeviceclass": "phone",
    "net": "network", "modem": "network",
    "media": "audio", "audioendpoint": "audio",
    "bluetooth": "bluetooth",
    "image": "camera", "camera": "camera",
    "keyboard": "input", "mouse": "input", "hidclass": "input",
}
#: Tur bermaydigan (dasturiy yoki boshqa hodisa egasi bor) sinflar.
#: Monitor - `multi_monitor` ning ishi.
_IGNORED_CLASSES = frozenset({
    "monitor", "printqueue", "softwaredevice", "softwarecomponent",
    "extension", "system", "computer", "volumesnapshot",
})
#: Shu sinflardagi tugunning nomi qurilmaning o'z nomi (tanlovda ustun).
_NAMED_CLASSES = frozenset({"diskdrive", "cdrom", "wpd", "camera", "image", "net"})
#: Telefon ba'zan "Image" (iPhone PTP) yoki "USB" sinfida keladi.
_PHONE_HINTS = ("iphone", "ipad", "android", "apple mobile device", "adb interface")
#: Konteyner FIZIK shinada bo'lishi shart (yuqoridagi docstring).
_WIRED_ENUMERATORS = frozenset({"USB", "USBSTOR", "UASPSTOR", "SD", "SDBUS"})

_USB_IDS = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.IGNORECASE)

#: Audio "shakli" (`PKEY_AudioEndpoint_FormFactor`). Ichki konteynerda
#: faqat shulari kuzatiladi - karnay/mikrofon emas, quloqqa taqiladigan.
_HEADPHONE_FORMS = frozenset({3, 5, 6})  # Headphones, Headset, Handset
#: Monitorning HDMI audiosi - `multi_monitor` ning ishi.
_DISPLAY_AUDIO_FORM = 9

#: Manbalar (`Peripheral.source`).
SOURCES = ("device", "drive", "audio")

_DRIVE_TYPE_TEXT = {2: "olinadigan", 3: "qattiq disk", 4: "tarmoq diski", 5: "CD/DVD", 6: "RAM disk"}


# --------------------------------------------------------------------------
# Ma'lumot
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DevNode:
    """SetupAPI'dagi bitta tugun (`group_devices` kirishi)."""

    instance_id: str
    device_class: str = ""
    name: str = ""
    container: str = ""

    @property
    def enumerator(self) -> str:
        return self.instance_id.split("\\", 1)[0].upper()


@dataclass(frozen=True)
class Peripheral:
    """
    Bitta kuzatiladigan narsa.

    `key`: `dev:<container>` | `drive:<harf>:<seriya>` | `audio:<endpoint>`.
    `container` audio uchun: u USB garnituraniki bo'lsa, garnitura
    qurilmasi uni o'zi aytadi va audio alohida hodisa bermaydi.
    """

    key: str
    kind: str
    label: str
    source: str  # "device" | "drive" | "audio"
    container: str = ""
    vid: str = ""
    pid: str = ""
    serial: str = ""
    drive_type: int = 0

    def payload(self, *, at_start: bool = False, drives=()) -> dict:
        data = {"kind": self.kind, "label": self.label[:120], "source": self.source}
        if self.vid:
            data.update(vid=self.vid, pid=self.pid)
        if self.serial:
            data["serial"] = self.serial
        drive_list = list(drives) or ([self.label] if self.source == "drive" else [])
        if drive_list:
            data["drives"] = [item[:120] for item in drive_list]
        if at_start:
            data["at_start"] = True
        return data


@dataclass
class Snapshot:
    """Bir lahzadagi holat. `failed` - shu safar o'qilmagan manbalar."""

    items: dict = field(default_factory=dict)
    failed: set = field(default_factory=set)


@dataclass(frozen=True)
class PeripheralEvent:
    type: str        # "peripheral_connected" | "peripheral_removed"
    severity: int
    payload: dict
    item: Peripheral


# --------------------------------------------------------------------------
# Sof mantiq
# --------------------------------------------------------------------------
def classify(nodes) -> tuple:
    """Konteyner turi va uni bergan tugun: `(kind | None, node | None)`."""
    best_rank, best_kind, best_node = len(_KIND_PRIORITY) * 2, None, None
    for node in nodes:
        cls = (node.device_class or "").strip().lower()
        if cls in _IGNORED_CLASSES:
            continue
        kind = _CLASS_KIND.get(cls, "other")
        name = (node.name or "").lower()
        if kind in ("camera", "other", "input") and any(hint in name for hint in _PHONE_HINTS):
            kind = "phone"
        # Bir tur ichida nomi ma'noli tugun: diskda "Kingston DataTraveler"
        # (DiskDrive), "Том"/"Volume" (tom) emas - amalda log'da shunday chiqdi.
        rank = _KIND_PRIORITY.index(kind) * 2 + (0 if cls in _NAMED_CLASSES else 1)
        if rank < best_rank:
            best_rank, best_kind, best_node = rank, kind, node
    return best_kind, best_node


def usb_ids(instance_id: str) -> tuple:
    """`USB\\VID_0951&PID_1666\\<seriya>` -> `(vid, pid, seriya)`."""
    match = _USB_IDS.search(instance_id or "")
    if not match:
        return "", "", ""
    parts = instance_id.split("\\")
    # Seriya raqami faqat oxirgi bo'lakda '&' bo'lmasa: aks holda bu
    # Windows bergan port izi ("6&1e2afdec&0&2"), qurilmaniki emas.
    serial = parts[2] if len(parts) == 3 and "&" not in parts[2] else ""
    return match.group(1).upper(), match.group(2).upper(), serial[:64]


def group_devices(nodes) -> dict:
    """Tugunlar -> `{dev:<container>: Peripheral}` (faqat tashqi, fizik)."""
    groups = defaultdict(list)
    for node in nodes:
        container = (node.container or "").lower()
        if container and container != ROOT_CONTAINER:
            groups[container].append(node)

    items = {}
    for container, group in groups.items():
        if not {node.enumerator for node in group} & _WIRED_ENUMERATORS:
            continue
        kind, source = classify(group)
        if kind is None:
            continue
        vid = pid = serial = ""
        for node in group:
            if node.enumerator == "USB":
                vid, pid, serial = usb_ids(node.instance_id)
                if vid:
                    break
        label = (source.name if source else "") or next(
            (node.name for node in group if node.name), "USB qurilma"
        )
        key = f"dev:{container}"
        items[key] = Peripheral(
            key=key, kind=kind, label=label, source="device",
            container=container, vid=vid, pid=pid, serial=serial,
        )
    return items


class PeripheralTracker:
    """
    Holatlar ketma-ketligi -> hodisalar.

    TASDIQLASH: yangi narsa ikkinchi ko'rinishda hodisa bo'ladi -
    Windows ba'zi tugunlarni bir lahzaga yaratib o'chiradi.

    BIRLASHTIRISH: fleshka uchun bitta hodisa, disk harfi bilan. Qurilma
    tom ulanishidan oldin chiqadi, shuning uchun disk/telefon
    `_STORAGE_WAIT` ko'rinishgacha yangi disk harfini kutadi. Kechikib
    kelgan harf `claim_window_s` ichida o'sha qurilmaga JIMGINA
    biriktiriladi (log'da qoladi). USB garnituraning audio qurilmalari
    garnituraga biriktiriladi.
    """

    _CONFIRM = 2
    _STORAGE_WAIT = 4

    def __init__(self, *, claim_window_s: float = 20.0) -> None:
        #: Boshlang'ich holati olingan manbalar. Boshida o'qilmagan manba
        #: birinchi muvaffaqiyatli o'qilishida JIM boshlang'ich oladi -
        #: aks holda undagi hamma narsa "imtihon davomida ulandi" bo'lardi.
        self._baselined: set = set()
        self._known: dict = {}
        #: Biriktirilgan (alohida hodisa bermaydigan) kalit -> egasi.
        self._parent: dict = {}
        self._pending: dict = {}
        #: Yaqinda ulangan disk/telefon: kalit -> vaqt.
        self._recent_storage: dict = {}
        self._claim_window = float(claim_window_s)

    @property
    def has_pending(self) -> bool:
        return bool(self._pending)

    # ------------------------------------------------------------------
    def start(self, snapshot: Snapshot, now: float = 0.0) -> list:
        """Boshlang'ich holat: shu paytda ulanganlar (`at_start`)."""
        self._known = dict(snapshot.items)
        self._parent.clear()
        self._pending.clear()
        self._recent_storage.clear()
        self._baselined = set(SOURCES) - set(snapshot.failed)
        items = snapshot.items

        devices = [item for item in items.values() if item.source == "device"]
        self._claim_children(devices, items.values())

        # Imtihon boshidagi disklar: qattiq disk (`C:`, `D:`) - ichki,
        # hodisa emas. Olinadigan disk yagona disk-qurilmaga tegishli
        # bo'lsa - o'shanga; aks holda alohida.
        storage = [item for item in devices if item.kind in ("storage", "phone")]
        loose_drives = []
        for item in items.values():
            if item.source != "drive" or item.drive_type == 3:
                continue
            if len(storage) == 1:
                self._parent[item.key] = storage[0].key
            else:
                loose_drives.append(item)

        events = []
        for item in devices:
            if item.kind in _QUIET_AT_START:
                continue
            drives = [
                d.label for d in items.values()
                if d.source == "drive" and self._parent.get(d.key) == item.key
            ]
            events.append(self._event("connected", item, at_start=True, drives=drives))
        for item in loose_drives:
            events.append(self._event("connected", item, at_start=True))
        for item in items.values():
            if item.source == "audio" and item.key not in self._parent:
                events.append(self._event("connected", item, at_start=True))
        return events

    def update(self, snapshot: Snapshot, now: float) -> list:
        events = []
        items = snapshot.items

        # 1. Uzilganlar. O'qilmagan manba - "o'zgarmadi", "hammasi uzildi" EMAS.
        for key in list(self._known):
            item = self._known[key]
            if key in items or item.source in snapshot.failed:
                continue
            del self._known[key]
            parent = self._parent.pop(key, None)
            self._recent_storage.pop(key, None)
            if parent is None:
                events.append(self._event("removed", item))
            else:
                log.info("Qurilma qismi uzildi: %s (%s)", item.label, parent)

        # Boshida o'qilmagan manba - endi jim boshlang'ich (`_baselined`).
        late = (set(SOURCES) - set(snapshot.failed)) - self._baselined
        if late:
            fresh = [item for item in items.values() if item.source in late]
            for item in fresh:
                self._known[item.key] = item
            devices = [item for item in self._known.values() if item.source == "device"]
            self._claim_children(devices, fresh)
            self._baselined |= late
            log.info("Qurilma manbai kechikib o'qildi (boshlang'ich): %s", ", ".join(sorted(late)))

        # 2. Yangilar - kutish ro'yxatiga; yo'qolgan kutayotgan - tashlanadi.
        for key in list(self._pending):
            if key not in items:
                del self._pending[key]
        for key, item in items.items():
            if key in self._known:
                continue
            _old, seen = self._pending.get(key, (item, 0))
            self._pending[key] = (item, seen + 1)

        # 3. Qurilmalar (avval - disk harflari va audio ularga biriktiriladi).
        new_drives = [
            item for item, _seen in self._pending.values() if item.source == "drive"
        ]
        for key, (item, seen) in list(self._pending.items()):
            if item.source != "device" or seen < self._CONFIRM:
                continue
            is_storage = item.kind in ("storage", "phone")
            if is_storage and not new_drives and seen < self._STORAGE_WAIT:
                continue
            drives = []
            if is_storage:
                for drive in new_drives:
                    self._adopt(drive, parent=key)
                    drives.append(drive.label)
                new_drives = []
                self._recent_storage[key] = now
            self._confirm(item)
            events.append(self._event("connected", item, drives=drives))

        # 4. Disk harflari va audio.
        for key, (item, seen) in list(self._pending.items()):
            if item.source == "device" or seen < self._CONFIRM:
                continue
            if item.source == "drive":
                if self._storage_pending():
                    continue  # fleshka hali tasdiqlanmagan - unga tegishli
                owner = self._recent_owner(now)
                if owner:
                    self._adopt(item, parent=owner)
                    log.info("Disk %s qurilmaga biriktirildi: %s", item.label, owner)
                    continue
            elif item.source == "audio":
                owner = self._device_of(item, items)
                if owner:
                    self._adopt(item, parent=owner)
                    continue
            self._confirm(item)
            events.append(self._event("connected", item))
        return events

    # ------------------------------------------------------------------
    def _claim_children(self, devices, items) -> None:
        """Audio qurilmalarni o'z USB qurilmasiga biriktiradi (boshlanishda)."""
        containers = {item.container: item.key for item in devices}
        for item in items:
            if item.source == "audio" and item.container in containers:
                self._parent[item.key] = containers[item.container]

    def _device_of(self, item: Peripheral, items: dict) -> str:
        key = f"dev:{item.container}" if item.container else ""
        return key if key and (key in items or key in self._known) else ""

    def _storage_pending(self) -> bool:
        return any(
            item.source == "device" and item.kind in ("storage", "phone")
            for item, _seen in self._pending.values()
        )

    def _recent_owner(self, now: float) -> str:
        for key, at in sorted(self._recent_storage.items(), key=lambda pair: -pair[1]):
            if key in self._known and now - at <= self._claim_window:
                return key
        return ""

    def _adopt(self, item: Peripheral, *, parent: str) -> None:
        self._pending.pop(item.key, None)
        self._known[item.key] = item
        self._parent[item.key] = parent

    def _confirm(self, item: Peripheral) -> None:
        self._pending.pop(item.key, None)
        self._known[item.key] = item

    @staticmethod
    def _event(action: str, item: Peripheral, *, at_start: bool = False, drives=()) -> PeripheralEvent:
        if action == "connected":
            severity = KIND_SEVERITY.get(item.kind, 1)
        else:
            # Uzilish - bayonnoma (ball emas): "qachon olib qo'yildi".
            severity = 0 if item.kind in ("input", "other") else 1
        return PeripheralEvent(
            type=f"peripheral_{action}",
            severity=severity,
            payload=item.payload(at_start=at_start, drives=drives),
            item=item,
        )


# --------------------------------------------------------------------------
# Windows manbalari
# --------------------------------------------------------------------------
def snapshot() -> Snapshot:
    """Uchala manba. Biri yiqilsa qolganlari baribir o'qiladi (`failed`)."""
    result = Snapshot()
    if not _IS_WINDOWS:
        result.failed.update(SOURCES)
        return result
    for source, reader in (("device", _device_items), ("drive", _drive_items), ("audio", _audio_items)):
        try:
            items = reader()
        except Exception:  # noqa: BLE001 - kuzatuv to'xtamasin
            log.debug("Qurilma manbai o'qilmadi: %s", source, exc_info=True)
            items = None
        if items is None:
            result.failed.add(source)
        else:
            result.items.update(items)
    return result


def suppress_error_dialogs() -> None:
    """
    Joriy THREAD da "Diskni qo'ying" oynasini o'chiradi.

    Bo'sh kartaridar yoki CD dagi `GetVolumeInformationW` Windows'da
    modal xato oynasini ochishi mumkin - kiosk ustida, talabgor oldida.
    """
    if not _IS_WINDOWS:
        return
    try:
        _kernel32.SetThreadErrorMode(_SEM_FAILCRITICALERRORS | _SEM_NOOPENFILEERRORBOX, None)
    except Exception:  # noqa: BLE001
        log.debug("SetThreadErrorMode ishlamadi", exc_info=True)


# --- SetupAPI -------------------------------------------------------------
_DIGCF_PRESENT = 0x2
_DIGCF_ALLCLASSES = 0x4
_SPDRP_DEVICEDESC = 0x0
_SPDRP_CLASS = 0x7
_SPDRP_FRIENDLYNAME = 0xC
_SPDRP_BASE_CONTAINERID = 0x24
_INVALID_HANDLE = ctypes.c_void_p(-1).value
#: Himoya chegarasi: oddiy mashinada 200-600 tugun.
_MAX_NODES = 5000


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("ClassGuid", ctypes.c_ubyte * 16),
        ("DevInst", ctypes.c_ulong),
        ("Reserved", ctypes.c_size_t),
    ]


def _device_items() -> Optional[dict]:
    nodes = _devnodes()
    return None if nodes is None else group_devices(nodes)


def _devnodes() -> Optional[list]:
    handle = _setupapi.SetupDiGetClassDevsW(None, None, None, _DIGCF_PRESENT | _DIGCF_ALLCLASSES)
    if not handle or handle == _INVALID_HANDLE:
        return None
    try:
        nodes = []
        data = _SP_DEVINFO_DATA()
        data.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
        index = 0
        while index < _MAX_NODES and _setupapi.SetupDiEnumDeviceInfo(handle, index, byref(data)):
            index += 1
            # Konteyner AVVAL: ichki qurilmalar (ko'pchilik) shu yerda
            # tushadi va qolgan xususiyatlar o'qilmaydi.
            container = _registry_string(handle, data, _SPDRP_BASE_CONTAINERID).lower()
            if not container or container == ROOT_CONTAINER:
                continue
            nodes.append(DevNode(
                instance_id=_instance_id(handle, data),
                device_class=_registry_string(handle, data, _SPDRP_CLASS),
                name=(_registry_string(handle, data, _SPDRP_FRIENDLYNAME)
                      or _registry_string(handle, data, _SPDRP_DEVICEDESC)),
                container=container,
            ))
        return nodes
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(handle)


def _registry_string(handle, data, prop: int) -> str:
    buffer = (ctypes.c_ubyte * 1024)()
    if not _setupapi.SetupDiGetDeviceRegistryPropertyW(
        handle, byref(data), prop, None, buffer, ctypes.sizeof(buffer), None
    ):
        return ""
    return ctypes.wstring_at(ctypes.addressof(buffer)).strip()


def _instance_id(handle, data) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    if not _setupapi.SetupDiGetDeviceInstanceIdW(handle, byref(data), buffer, len(buffer), None):
        return ""
    return buffer.value


# --- Disklar --------------------------------------------------------------
_SEM_FAILCRITICALERRORS = 0x0001
_SEM_NOOPENFILEERRORBOX = 0x8000


def _drive_items() -> dict:
    items = {}
    mask = _kernel32.GetLogicalDrives()
    for bit in range(26):
        if not mask & (1 << bit):
            continue
        letter = chr(ord("A") + bit)
        root = f"{letter}:\\"
        drive_type = _kernel32.GetDriveTypeW(root)
        if drive_type not in _DRIVE_TYPE_TEXT:
            continue
        volume, serial, size = "", 0, ""
        if drive_type != 4:
            # Tarmoq diski so'ralmaydi: server javob bermasa bu chaqiruv
            # o'nlab soniya osiladi.
            name = ctypes.create_unicode_buffer(261)
            serial_number = ctypes.c_ulong(0)
            ok = _kernel32.GetVolumeInformationW(
                root, name, len(name), byref(serial_number), None, None, None, 0
            )
            if not ok and drive_type in (2, 5):
                continue  # bo'sh kartaridar / CD - tashuvchi yo'q
            volume, serial = name.value, serial_number.value
            total = ctypes.c_ulonglong(0)
            if _kernel32.GetDiskFreeSpaceExW(root, None, byref(total), None) and total.value:
                size = f"{total.value / 1024 ** 3:.1f} GB"
        label = " ".join(part for part in (f"{letter}:", volume, size, f"({_DRIVE_TYPE_TEXT[drive_type]})") if part)
        key = f"drive:{letter}:{serial:08X}"
        items[key] = Peripheral(
            key=key, kind="storage", label=label, source="drive", drive_type=drive_type,
        )
    return items


# --- Audio (Core Audio, COM) ----------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def text(self) -> str:
        tail = bytes(self.Data4)
        return "{%08x-%04x-%04x-%s-%s}" % (
            self.Data1, self.Data2, self.Data3, tail[:2].hex(), tail[2:].hex()
        )


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    """`PROPVARIANT` (x64 - 24 bayt): bizga `vt` va birinchi qiymat kerak."""

    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("value", ctypes.c_ulonglong),
        ("tail", ctypes.c_ulonglong),
    ]


_VT_UI4 = 19
_VT_LPWSTR = 31
_VT_CLSID = 72
_E_ALL = 2
_DEVICE_STATE_ACTIVE = 0x1
_STGM_READ = 0
_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2


def _guid(text: str) -> _GUID:
    value = _GUID()
    _ole32.CLSIDFromString(text, byref(value))
    return value


def _key(fmtid: str, pid: int) -> _PROPERTYKEY:
    return _PROPERTYKEY(_guid(fmtid), pid)


def _vcall(pointer, index: int, *argtypes):
    """COM metodi (`dshow._vcall` bilan bir xil; `argtypes` majburiy)."""
    vtable = ctypes.cast(pointer, POINTER(POINTER(c_void_p)))[0]
    return ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)(vtable[index])


def _release(pointer) -> None:
    if pointer:
        _vcall(pointer, 2)(pointer)


def _audio_items() -> Optional[dict]:
    initialized = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # `RPC_E_CHANGED_MODE` - boshqa rejimda allaqachon ochiq: ishlaydi,
    # lekin `CoUninitialize` bizniki emas (`dshow._enumerate` bilan bir xil).
    own_com = initialized in (0, 1)
    enumerator = c_void_p()
    try:
        if _ole32.CoCreateInstance(
            byref(_CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
            byref(_IID_IMMDeviceEnumerator), byref(enumerator),
        ) != 0 or not enumerator:
            return None
        try:
            return _active_endpoints(enumerator)
        finally:
            _release(enumerator)
    finally:
        if own_com:
            _ole32.CoUninitialize()


def _active_endpoints(enumerator) -> Optional[dict]:
    collection = c_void_p()
    enum = _vcall(enumerator, 3, ctypes.c_int, ctypes.c_ulong, POINTER(c_void_p))
    if enum(enumerator, _E_ALL, _DEVICE_STATE_ACTIVE, byref(collection)) != 0 or not collection:
        return None
    try:
        count = ctypes.c_uint(0)
        if _vcall(collection, 3, POINTER(ctypes.c_uint))(collection, byref(count)) != 0:
            return None
        item = _vcall(collection, 4, ctypes.c_uint, POINTER(c_void_p))
        items = {}
        for index in range(min(count.value, 128)):
            device = c_void_p()
            if item(collection, index, byref(device)) != 0 or not device:
                continue
            try:
                endpoint = _endpoint(device)
            finally:
                _release(device)
            if endpoint is not None:
                items[endpoint.key] = endpoint
        return items
    finally:
        _release(collection)


def _endpoint(device) -> Optional[Peripheral]:
    raw_id = c_void_p()
    if _vcall(device, 5, POINTER(c_void_p))(device, byref(raw_id)) != 0 or not raw_id:
        return None
    try:
        endpoint_id = ctypes.wstring_at(raw_id.value)
    finally:
        _ole32.CoTaskMemFree(raw_id)

    store = c_void_p()
    if _vcall(device, 4, ctypes.c_ulong, POINTER(c_void_p))(device, _STGM_READ, byref(store)) != 0 or not store:
        return None
    try:
        name = _property(store, _PKEY_FriendlyName)
        form = _property(store, _PKEY_FormFactor)
        container = _property(store, _PKEY_ContainerId)
    finally:
        _release(store)
    return audio_endpoint(endpoint_id, name, form, container)


def audio_endpoint(endpoint_id: str, name, form, container) -> Optional[Peripheral]:
    """Audio qurilma kuzatiladimi (sof qoida - testlanadi)."""
    container = (container or "").lower() if isinstance(container, str) else ""
    form = form if isinstance(form, int) else -1
    if form == _DISPLAY_AUDIO_FORM:
        return None
    if (not container or container == ROOT_CONTAINER) and form not in _HEADPHONE_FORMS:
        return None  # ichki karnay/mikrofon
    flow = "mikrofon" if endpoint_id.startswith("{0.0.1.") else "audio"
    label = name if isinstance(name, str) and name else f"Audio qurilma ({flow})"
    return Peripheral(
        key=f"audio:{endpoint_id}", kind="audio", label=label, source="audio",
        container="" if container == ROOT_CONTAINER else container,
    )


def _property(store, key: _PROPERTYKEY):
    value = _PROPVARIANT()
    get_value = _vcall(store, 5, POINTER(_PROPERTYKEY), POINTER(_PROPVARIANT))
    if get_value(store, byref(key), byref(value)) != 0:
        return None
    try:
        if value.vt == _VT_LPWSTR and value.value:
            return ctypes.wstring_at(value.value)
        if value.vt == _VT_UI4:
            return int(value.value & 0xFFFFFFFF)
        if value.vt == _VT_CLSID and value.value:
            return ctypes.cast(c_void_p(value.value), POINTER(_GUID))[0].text()
        return None
    finally:
        _ole32.PropVariantClear(byref(value))


def _setup_prototypes() -> None:
    """`argtypes` MAJBURIY - usiz 64-bitli deskriptor buziladi (CLAUDE.md)."""
    wt = ctypes.wintypes
    _setupapi.SetupDiGetClassDevsW.argtypes = [c_void_p, ctypes.c_wchar_p, c_void_p, wt.DWORD]
    _setupapi.SetupDiGetClassDevsW.restype = c_void_p
    _setupapi.SetupDiEnumDeviceInfo.argtypes = [c_void_p, wt.DWORD, POINTER(_SP_DEVINFO_DATA)]
    _setupapi.SetupDiEnumDeviceInfo.restype = wt.BOOL
    _setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
        c_void_p, POINTER(_SP_DEVINFO_DATA), wt.DWORD, POINTER(wt.DWORD),
        c_void_p, wt.DWORD, POINTER(wt.DWORD),
    ]
    _setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wt.BOOL
    _setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
        c_void_p, POINTER(_SP_DEVINFO_DATA), ctypes.c_wchar_p, wt.DWORD, POINTER(wt.DWORD),
    ]
    _setupapi.SetupDiGetDeviceInstanceIdW.restype = wt.BOOL
    _setupapi.SetupDiDestroyDeviceInfoList.argtypes = [c_void_p]
    _setupapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL

    _kernel32.GetLogicalDrives.argtypes = []
    _kernel32.GetLogicalDrives.restype = wt.DWORD
    _kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    _kernel32.GetDriveTypeW.restype = ctypes.c_uint
    _kernel32.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_wchar_p, wt.DWORD, POINTER(wt.DWORD),
        POINTER(wt.DWORD), POINTER(wt.DWORD), ctypes.c_wchar_p, wt.DWORD,
    ]
    _kernel32.GetVolumeInformationW.restype = wt.BOOL
    _kernel32.GetDiskFreeSpaceExW.argtypes = [
        ctypes.c_wchar_p, POINTER(ctypes.c_ulonglong), POINTER(ctypes.c_ulonglong),
        POINTER(ctypes.c_ulonglong),
    ]
    _kernel32.GetDiskFreeSpaceExW.restype = wt.BOOL
    _kernel32.SetThreadErrorMode.argtypes = [wt.DWORD, POINTER(wt.DWORD)]
    _kernel32.SetThreadErrorMode.restype = wt.BOOL

    _ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, POINTER(_GUID)]
    _ole32.CLSIDFromString.restype = ctypes.c_long
    _ole32.CoInitializeEx.argtypes = [c_void_p, wt.DWORD]
    _ole32.CoInitializeEx.restype = ctypes.c_long
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None
    _ole32.CoCreateInstance.argtypes = [
        POINTER(_GUID), c_void_p, wt.DWORD, POINTER(_GUID), POINTER(c_void_p),
    ]
    _ole32.CoCreateInstance.restype = ctypes.c_long
    _ole32.CoTaskMemFree.argtypes = [c_void_p]
    _ole32.CoTaskMemFree.restype = None
    _ole32.PropVariantClear.argtypes = [POINTER(_PROPVARIANT)]
    _ole32.PropVariantClear.restype = ctypes.c_long


if _IS_WINDOWS:
    import ctypes.wintypes  # noqa: F401 - `_setup_prototypes` ishlatadi

    _setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    _setup_prototypes()
    _CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
    _IID_IMMDeviceEnumerator = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _PKEY_FriendlyName = _key("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)
    _PKEY_FormFactor = _key("{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E}", 0)
    _PKEY_ContainerId = _key("{8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C}", 2)
else:  # pragma: no cover - loyiha Windows uchun
    _setupapi = _kernel32 = _ole32 = None
