"""
Xost (Debian VM) ko'rsatkichlari: CPU, xotira, disk, tarmoq, soketlar,
systemd servislari, virtualizatsiya va vaqt sinxronizatsiyasi.

Har funksiya ikki narsa qaytaradi: `data` (hozirgi holat) va
`counters` (o'sib boruvchi hisoblagichlar). Tezliklar (`/s`, CPU foizi)
hisoblagichlardan `store.compute_rates` bilan chiqariladi — bloklovchi
`psutil.cpu_percent(interval=...)` ishlatilmaydi: u har so'rovda
worker thread'ini uxlatib qo'yardi.

Linux'ga xos manbalar (`/proc/net/tcp`, `/proc/pressure`, systemd) yo'q
bo'lsa (dev — Windows) bo'lim `available: False` bilan qaytadi, xato emas.
"""

from __future__ import annotations

import fnmatch
import functools
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
from django.conf import settings

logger = logging.getLogger(__name__)

IS_LINUX = sys.platform.startswith("linux")
_SUBPROCESS_TIMEOUT = 2.0


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _run(*args: str) -> str | None:
    """Tashqi buyruq (systemctl va h.k.); topilmasa yoki xato — `None`."""
    if shutil.which(args[0]) is None:
        return None
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Monitoring: %s ishlamadi: %s", args[0], exc)
        return None
    return result.stdout


# --------------------------------------------------------------------------
# O'zgarmas ma'lumot (OS, CPU modeli, virtualizatsiya)
# --------------------------------------------------------------------------
def _os_name() -> str:
    release = _read("/etc/os-release")
    if release:
        match = re.search(r'^PRETTY_NAME="?([^"\n]+)"?', release, re.MULTILINE)
        if match:
            return match.group(1)
    return platform.platform(terse=True)


def _cpu_model() -> str:
    info = _read("/proc/cpuinfo")
    if info:
        match = re.search(r"^model name\s*:\s*(.+)$", info, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return platform.processor() or ""


@functools.lru_cache(maxsize=1)
def _static_info() -> dict:
    """Jarayon hayoti davomida o'zgarmaydi — bir marta o'qiladi."""
    return {
        "os": _os_name(),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "cpu_model": _cpu_model(),
        "cpu_logical": psutil.cpu_count(logical=True) or 0,
        "cpu_physical": psutil.cpu_count(logical=False) or 0,
    }


def _virtualization() -> dict:
    """
    Gipervizor: `systemd-detect-virt` (eng ishonchli), bo'lmasa DMI.

    ESXi'da VMware Tools (`open-vm-tools`) muhim: xostdan to'g'ri
    o'chirish/qayta yoqish, vaqt sinxronizatsiyasi va xotira
    "balloon" drayveri. Yo'qligi — ogohlantirish (`services.problems`).
    """
    kind = (_run("systemd-detect-virt") or "").strip() or None
    vendor = _read("/sys/class/dmi/id/sys_vendor")
    product = _read("/sys/class/dmi/id/product_name")
    if kind is None and vendor:
        lowered = vendor.lower()
        if "vmware" in lowered:
            kind = "vmware"
        elif "qemu" in lowered or "kvm" in lowered:
            kind = "kvm"
        elif "microsoft" in lowered and product and "virtual" in product.lower():
            kind = "microsoft"
    tools = None
    if kind == "vmware":
        tools = any(
            (proc.info.get("name") or "") == "vmtoolsd"
            for proc in psutil.process_iter(["name"])
        )
    return {
        "type": None if kind in (None, "none") else kind,
        "vendor": vendor,
        "product": product,
        "vmware_tools": tools,
    }


def _time_sync() -> dict:
    """
    Soat sinxronmi (NTP). Heartbeat, `close_stale_sessions` va dalil
    vaqtlari server soatiga tayanadi — soat siljisa sessiyalar "eskiradi".
    """
    output = _run("timedatectl", "show", "-p", "NTPSynchronized", "-p", "Timezone")
    if output is None:
        return {"available": False}
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    synced = values.get("NTPSynchronized")
    return {
        "available": True,
        "synced": None if synced is None else synced == "yes",
        "timezone": values.get("Timezone") or None,
    }


_slow_cache: dict[str, tuple[float, object]] = {}


def _cached(name: str, ttl: float, build):
    """Sekin o'zgaradigan qiymatlar (VM, NTP) — jarayon ichida qisqa kesh."""
    now = time.monotonic()
    hit = _slow_cache.get(name)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = build()
    _slow_cache[name] = (now, value)
    return value


def platform_info() -> dict:
    boot = psutil.boot_time()
    return {
        "hostname": platform.node(),
        **_static_info(),
        "boot_time": boot,
        "uptime_s": max(0, int(time.time() - boot)),
        "virtualization": _cached("virt", 300, _virtualization),
        "time_sync": _cached("ntp", 60, _time_sync),
    }


# --------------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------------
#: Linux'da `guest`/`guest_nice` allaqachon `user`/`nice` ichida —
#: qo'shilsa jami ikki marta sanalardi.
_CPU_EXCLUDE = {"guest", "guest_nice"}


def cpu() -> tuple[dict, dict]:
    counters: dict[str, float] = {}
    total = psutil.cpu_times()
    for field, value in total._asdict().items():
        if field not in _CPU_EXCLUDE:
            counters[f"cpu.{field}"] = float(value)
    for index, core in enumerate(psutil.cpu_times(percpu=True)):
        fields = core._asdict()
        counters[f"core.{index}.total"] = float(
            sum(v for k, v in fields.items() if k not in _CPU_EXCLUDE)
        )
        counters[f"core.{index}.idle"] = float(fields.get("idle", 0) + fields.get("iowait", 0))

    try:
        load = os.getloadavg() if hasattr(os, "getloadavg") else psutil.getloadavg()
    except OSError:
        load = (0.0, 0.0, 0.0)
    return {"load": [round(value, 2) for value in load]}, counters


def cpu_from_rates(data: dict, rates: dict) -> dict:
    """CPU foizlari: hisoblagich farqidan (oyna — oxirgi namunadan beri)."""
    fields = {
        name.split(".", 1)[1]: value
        for name, value in rates.items()
        if name.startswith("cpu.")
    }
    total = sum(fields.values())
    cores = _static_info()["cpu_logical"] or 1
    load = data.get("load") or [0, 0, 0]
    result = {
        **data,
        "load_per_core": round(load[0] / cores, 2),
        "percent": None,
        "breakdown": {},
        "cores": [],
    }
    if total <= 0:
        return result

    def pct(*names):
        return round(sum(fields.get(name, 0.0) for name in names) / total * 100, 1)

    idle = pct("idle")
    iowait = pct("iowait")
    result["percent"] = round(max(0.0, 100 - idle - iowait), 1)
    result["breakdown"] = {
        "user": pct("user", "nice"),
        "system": pct("system"),
        "iowait": iowait,
        # ESXi'da eng muhim belgi: VM navbat kutyapti (xost band).
        "steal": pct("steal"),
        "irq": pct("irq", "softirq", "interrupt", "dpc"),
    }
    core_count = len([1 for name in rates if name.endswith(".total") and name.startswith("core.")])
    for index in range(core_count):
        core_total = rates.get(f"core.{index}.total") or 0
        core_idle = rates.get(f"core.{index}.idle") or 0
        busy = 0.0 if core_total <= 0 else (1 - core_idle / core_total) * 100
        result["cores"].append(round(min(100.0, max(0.0, busy)), 1))
    return result


# --------------------------------------------------------------------------
# Xotira va bosim (PSI)
# --------------------------------------------------------------------------
def memory() -> tuple[dict, dict]:
    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()
    used = virtual.total - virtual.available
    data = {
        "total": virtual.total,
        "available": virtual.available,
        # "Ishlatilgan" = jami − mavjud: kesh (page cache) bo'sh xotira
        # hisoblanadi — Linux uni darhol bo'shatadi. `virtual.used` ni
        # ko'rsatish administratorni chalg'itardi.
        "used": used,
        "percent": round(used / virtual.total * 100, 1) if virtual.total else 0,
        "cached": getattr(virtual, "cached", 0) + getattr(virtual, "buffers", 0),
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_percent": round(swap.percent, 1),
    }
    counters = {"swap.sin": float(swap.sin or 0), "swap.sout": float(swap.sout or 0)}
    return data, counters


def pressure() -> dict:
    """
    Linux PSI (`/proc/pressure/*`): resurs yetmay KUTILGAN vaqt ulushi.

    Foizdan aniqroq "to'yinish" belgisi: CPU 85% bo'lsa ham hech kim
    kutmasligi mumkin, PSI `some` esa aynan kechikishni ko'rsatadi.
    Yadro PSI'siz yig'ilgan bo'lsa (`psi=0`) — `None`.
    """
    result = {}
    for resource in ("cpu", "memory", "io"):
        text = _read(f"/proc/pressure/{resource}")
        if not text:
            continue
        parsed = {}
        for line in text.splitlines():
            parts = line.split()
            if not parts:
                continue
            values = dict(part.split("=", 1) for part in parts[1:] if "=" in part)
            try:
                parsed[parts[0]] = {
                    "avg10": float(values.get("avg10", 0)),
                    "avg60": float(values.get("avg60", 0)),
                    "avg300": float(values.get("avg300", 0)),
                }
            except ValueError:
                continue
        if parsed:
            result[resource] = parsed
    return result or None


def kernel_limits() -> dict:
    """Ochiq fayllar va TCP soketlar (TIME_WAIT) — tizim bo'ylab."""
    data: dict = {}
    file_nr = _read("/proc/sys/fs/file-nr")
    if file_nr:
        parts = file_nr.split()
        if len(parts) >= 3:
            allocated, maximum = int(parts[0]), int(parts[2])
            data["files_open"] = allocated
            data["files_max"] = maximum
            data["files_percent"] = round(allocated / maximum * 100, 1) if maximum else None
    sockstat = _read("/proc/net/sockstat")
    if sockstat:
        match = re.search(r"^TCP:\s+(.*)$", sockstat, re.MULTILINE)
        if match:
            tokens = match.group(1).split()
            values = dict(zip(tokens[::2], tokens[1::2]))
            data["tcp_inuse"] = int(values.get("inuse", 0))
            # Ko'p TIME_WAIT — kimdir har so'rovga yangi TCP ochyapti
            # (yuklama sinovida channels_redis shunday qilgan edi).
            data["tcp_time_wait"] = int(values.get("tw", 0))
            data["tcp_orphan"] = int(values.get("orphan", 0))
    return data


# --------------------------------------------------------------------------
# Disklar
# --------------------------------------------------------------------------
_REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "ntfs", "refs"}
_SKIP_MOUNT_PREFIXES = ("/snap", "/var/lib/docker", "/run", "/boot/efi", "/var/snap")
#: Butun disk (bo'limlar emas) — ESXi'da odatda `sda`, `sdb`.
_WHOLE_DISK_RE = re.compile(r"^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+n\d+|PhysicalDrive\d+)$")


def data_paths(extra: dict[str, str | None] | None = None) -> dict[str, str]:
    """Ilova ma'lumoti qaysi katalogda — disk kartasida "bu yerda nima bor"."""
    paths = {
        "screenshots": str(settings.SCREENSHOT_STORAGE["ROOT"]),
        "logs": str(Path(settings.CLIENT_ACCESS_LOG).resolve().parent),
        "app": str(Path(settings.BASE_DIR).resolve()),
    }
    for name, value in (extra or {}).items():
        if value:
            paths[name] = value
    return paths


def _mount_for(path: str, mounts: list[str]) -> str | None:
    """Yo'l qaysi mount nuqtasida: eng uzun mos prefiks (mavjud ota katalog)."""
    candidate = Path(path)
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    try:
        real = os.path.realpath(candidate)
    except OSError:
        return None
    real = os.path.normcase(real)
    best = None
    for mount in mounts:
        # Ikkala tomon ham `realpath`: Windows qisqa nomlari (`Y82AF~1`)
        # va Linux'dagi symlink'lar prefiks solishtirishni buzmasin.
        try:
            normalized = os.path.normcase(os.path.realpath(mount))
        except OSError:
            normalized = os.path.normcase(mount)
        prefix = normalized if normalized.endswith(os.sep) else normalized + os.sep
        if real == normalized or real.startswith(prefix):
            if best is None or len(mount) > len(best):
                best = mount
    return best


def disks(paths: dict[str, str]) -> tuple[dict, dict]:
    mounts = []
    seen_devices = set()
    for part in psutil.disk_partitions(all=False):
        fstype = (part.fstype or "").lower()
        if fstype not in _REAL_FS:
            continue
        if part.mountpoint.startswith(_SKIP_MOUNT_PREFIXES):
            continue
        if part.device in seen_devices:
            continue
        seen_devices.add(part.device)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        entry = {
            "mount": part.mountpoint,
            "device": part.device,
            "fstype": fstype,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.percent, 1),
            "inodes_percent": None,
            "contains": [],
        }
        if hasattr(os, "statvfs"):
            try:
                stat = os.statvfs(part.mountpoint)
                if stat.f_files:
                    entry["inodes_percent"] = round((1 - stat.f_ffree / stat.f_files) * 100, 1)
            except OSError:
                pass
        mounts.append(entry)

    mount_points = [entry["mount"] for entry in mounts]
    for name, path in paths.items():
        mount = _mount_for(path, mount_points)
        for entry in mounts:
            if entry["mount"] == mount:
                entry["contains"].append(name)

    counters: dict[str, float] = {}
    devices = []
    try:
        io = psutil.disk_io_counters(perdisk=True) or {}
    except (OSError, RuntimeError):
        io = {}
    for name, stat in io.items():
        if not _WHOLE_DISK_RE.match(name):
            continue
        devices.append(name)
        fields = stat._asdict()
        for field in ("read_bytes", "write_bytes", "read_count", "write_count", "read_time", "write_time", "busy_time"):
            if field in fields:
                counters[f"disk.{name}.{field}"] = float(fields[field])
    return {"mounts": mounts, "devices": sorted(devices)}, counters


def disks_from_rates(data: dict, rates: dict) -> dict:
    io = []
    for name in data.get("devices", []):
        def rate(field, _name=name):
            return rates.get(f"disk.{_name}.{field}")

        reads, writes = rate("read_count"), rate("write_count")
        if reads is None and writes is None:
            continue
        ops = (reads or 0) + (writes or 0)
        busy = rate("busy_time")  # ms/s
        io_time = (rate("read_time") or 0) + (rate("write_time") or 0)
        io.append({
            "device": name,
            "read_bps": round(rate("read_bytes") or 0),
            "write_bps": round(rate("write_bytes") or 0),
            "read_iops": round(reads or 0, 1),
            "write_iops": round(writes or 0, 1),
            # `%util` (iostat): qurilma band bo'lgan vaqt ulushi.
            "util_pct": None if busy is None else round(min(100.0, busy / 10), 1),
            # O'rtacha javob vaqti (iostat `await`): ESXi datastore sekinligi
            # aynan shu yerda ko'rinadi.
            "await_ms": round(io_time / ops, 2) if ops > 0 else 0.0,
        })
    return {"mounts": data.get("mounts", []), "io": io}


# --------------------------------------------------------------------------
# Tarmoq
# --------------------------------------------------------------------------
_SKIP_NIC_PREFIXES = ("lo", "veth", "docker", "br-", "virbr", "Loopback")


def network() -> tuple[dict, dict]:
    counters: dict[str, float] = {}
    interfaces = []
    stats = psutil.net_if_stats()
    for name, io in (psutil.net_io_counters(pernic=True) or {}).items():
        if name.startswith(_SKIP_NIC_PREFIXES):
            continue
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        interfaces.append({"name": name, "speed_mbps": getattr(stat, "speed", 0) or 0})
        for field in ("bytes_sent", "bytes_recv", "errin", "errout", "dropin", "dropout"):
            counters[f"net.{name}.{field}"] = float(getattr(io, field, 0))
    return {"interfaces": interfaces}, counters


def network_from_rates(data: dict, rates: dict) -> dict:
    result = []
    for nic in data.get("interfaces", []):
        name = nic["name"]
        rx = rates.get(f"net.{name}.bytes_recv")
        tx = rates.get(f"net.{name}.bytes_sent")
        speed = nic["speed_mbps"]
        util = None
        if speed and rx is not None and tx is not None:
            util = round(max(rx, tx) * 8 / (speed * 1_000_000) * 100, 1)
        errors = sum(
            rates.get(f"net.{name}.{field}") or 0 for field in ("errin", "errout", "dropin", "dropout")
        )
        result.append({
            **nic,
            "rx_bps": None if rx is None else round(rx),
            "tx_bps": None if tx is None else round(tx),
            "util_pct": util,
            "errors_per_s": round(errors, 2),
        })
    return {"interfaces": result}


# --------------------------------------------------------------------------
# Tinglanayotgan portlar: qabul navbati va ulanishlar
# --------------------------------------------------------------------------
DEFAULT_PORTS = {
    "nginx_https": 443,
    "nginx_http": 80,
    "api": 8002,
    "ws": 8003,
    "pgbouncer": 6432,
    "postgres": 5432,
    "redis": 6379,
}


def configured_ports() -> dict[str, int]:
    raw = settings.SYSTEM_MONITOR.get("PORTS") or []
    if not raw:
        return dict(DEFAULT_PORTS)
    ports = {}
    for item in raw:
        name, _, port = item.partition(":")
        if name and port.isdigit():
            ports[name.strip()] = int(port)
    return ports or dict(DEFAULT_PORTS)


def _proc_net_tcp() -> list[tuple[int, str, int]] | None:
    """`/proc/net/tcp{,6}`: (lokal port, holat, rx_queue)."""
    rows = []
    found = False
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, encoding="ascii") as handle:
                found = True
                next(handle, None)
                for line in handle:
                    parts = line.split(None, 5)
                    if len(parts) < 5:
                        continue
                    local, state, queues = parts[1], parts[3], parts[4]
                    port = int(local.rsplit(":", 1)[1], 16)
                    rx_queue = int(queues.split(":")[1], 16)
                    rows.append((port, state, rx_queue))
        except (OSError, ValueError, IndexError):
            continue
    return rows if found else None


def sockets() -> dict:
    """
    Har port bo'yicha: tinglanyaptimi, qabul navbati (backlog), ulanishlar.

    `/proc/net/tcp` hamma uchun o'qiladi (root kerak emas). LISTEN
    qatoridagi `rx_queue` — `accept()` kutayotgan ulanishlar soni
    (`ss -ltn` dagi Recv-Q): u o'ssa gunicorn worker'lari ulgurmayapti.
    `ws` portidagi ESTABLISHED — nginx -> uvicorn, ya'ni WebSocket
    ulanishlari soni.
    """
    ports = configured_ports()
    wanted = {port: name for name, port in ports.items()}
    result = {name: {"port": port, "listening": False, "backlog": 0, "established": 0} for name, port in ports.items()}
    rows = _proc_net_tcp()
    if rows is not None:
        for port, state, rx_queue in rows:
            name = wanted.get(port)
            if name is None:
                continue
            entry = result[name]
            if state == "0A":  # LISTEN
                entry["listening"] = True
                entry["backlog"] += rx_queue
            elif state == "01":  # ESTABLISHED
                entry["established"] += 1
        source = "proc"
    else:
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.AccessDenied, OSError):
            return {"available": False, "ports": []}
        for conn in connections:
            if not conn.laddr:
                continue
            name = wanted.get(conn.laddr.port)
            if name is None:
                continue
            if conn.status == psutil.CONN_LISTEN:
                result[name]["listening"] = True
            elif conn.status == psutil.CONN_ESTABLISHED:
                result[name]["established"] += 1
        source = "psutil"
    listed = [{"name": name, **values} for name, values in result.items() if values["listening"]]
    return {"available": True, "source": source, "ports": listed}


# --------------------------------------------------------------------------
# systemd servislari
# --------------------------------------------------------------------------
#: (glob, nom, guruh, majburiymi)
DEFAULT_UNITS: list[tuple[str, str, str, bool]] = [
    ("proctoring-api.service", "HTTP API (gunicorn)", "app", True),
    ("proctoring-ws.service", "WebSocket (uvicorn)", "app", True),
    ("proctoring-celery-ingest.service", "Celery — ingest", "app", True),
    ("proctoring-celery-maintenance.service", "Celery — maintenance", "app", True),
    ("proctoring-celery-beat.service", "Celery — beat", "app", True),
    ("nginx.service", "nginx", "infra", True),
    ("postgresql@*.service", "PostgreSQL", "infra", True),
    ("redis-server.service", "Redis", "infra", True),
    ("pgbouncer.service", "PgBouncer", "infra", False),
    ("open-vm-tools.service", "VMware Tools", "vm", False),
]

_SHOW_PROPS = (
    "Id,LoadState,ActiveState,SubState,MainPID,NRestarts,Result,"
    "ActiveEnterTimestampMonotonic,MemoryCurrent,CPUUsageNSec,TasksCurrent"
)
#: systemd "qiymat yo'q" ni UINT64_MAX bilan beradi.
_UINT64_MAX = 2**64 - 1


def _unit_specs() -> list[tuple[str, str, str, bool]]:
    custom = settings.SYSTEM_MONITOR.get("UNITS") or []
    if not custom:
        return DEFAULT_UNITS
    specs = []
    for item in custom:
        pattern = item if "." in item else f"{item}.service"
        specs.append((pattern, item, "app", True))
    return specs


def _resolve_units(specs) -> list[tuple[str, str, str, bool]]:
    """Glob'li unit'larni haqiqiy nomga ochadi (`postgresql@15-main`)."""
    globs = [spec[0] for spec in specs if any(ch in spec[0] for ch in "*?[")]
    loaded: list[str] = []
    if globs:
        output = _run(
            "systemctl", "list-units", "--all", "--plain", "--no-legend", "--no-pager",
            "--type=service", *globs,
        ) or ""
        loaded = [line.split()[0] for line in output.splitlines() if line.strip()]
    resolved = []
    for pattern, label, group, required in specs:
        if any(ch in pattern for ch in "*?["):
            matches = [unit for unit in loaded if fnmatch.fnmatch(unit, pattern)]
            if not matches:
                resolved.append((pattern.replace("@*", ""), label, group, required))
            for unit in matches:
                suffix = unit.split("@", 1)[1].rsplit(".", 1)[0] if "@" in unit else ""
                resolved.append((unit, f"{label} {suffix}".strip(), group, required))
        else:
            resolved.append((pattern, label, group, required))
    return resolved


def _int(value: str | None) -> int | None:
    if value in (None, "", "[not set]"):
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return None if number == _UINT64_MAX else number


def services() -> tuple[dict, dict]:
    """
    systemd unit'lari: holati, qayta ishga tushishlar soni, xotira, CPU.

    `systemctl show` oddiy foydalanuvchiga ham ruxsat etilgan (D-Bus
    orqali faqat o'qish). Bitta chaqiruvda barcha unit'lar — har biriga
    alohida jarayon ochilmaydi.
    """
    if not IS_LINUX or shutil.which("systemctl") is None:
        return {"available": False, "units": []}, {}
    specs = _resolve_units(_unit_specs())
    output = _run("systemctl", "show", "--no-pager", "-p", _SHOW_PROPS, *[spec[0] for spec in specs])
    if output is None:
        return {"available": False, "units": []}, {}

    blocks = [block for block in output.strip().split("\n\n") if block.strip()]
    parsed = {}
    for block in blocks:
        values = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if values.get("Id"):
            parsed[values["Id"]] = values

    now_mono = time.monotonic()
    units, counters = [], {}
    for unit, label, group, required in specs:
        values = parsed.get(unit) or {}
        load_state = values.get("LoadState") or "not-found"
        if load_state == "not-found" and not required:
            continue
        since_us = _int(values.get("ActiveEnterTimestampMonotonic"))
        active = values.get("ActiveState") or "unknown"
        cpu_ns = _int(values.get("CPUUsageNSec"))
        if cpu_ns is not None:
            counters[f"svc.{unit}.cpu_ns"] = float(cpu_ns)
        units.append({
            "unit": unit,
            "label": label,
            "group": group,
            "required": required,
            "load_state": load_state,
            "active_state": active,
            "sub_state": values.get("SubState") or "",
            "result": values.get("Result") or "",
            "main_pid": _int(values.get("MainPID")) or None,
            "restarts": _int(values.get("NRestarts")) or 0,
            "uptime_s": (
                int(now_mono - since_us / 1_000_000)
                if active == "active" and since_us else None
            ),
            "memory": _int(values.get("MemoryCurrent")),
            "tasks": _int(values.get("TasksCurrent")),
        })
    return {"available": True, "units": units}, counters


def services_from_rates(data: dict, rates: dict) -> dict:
    for unit in data.get("units", []):
        rate = rates.get(f"svc.{unit['unit']}.cpu_ns")
        # 100% = bitta yadro to'liq (top/htop'dagi kabi).
        unit["cpu_pct"] = None if rate is None else round(rate / 1e9 * 100, 1)
    return data
