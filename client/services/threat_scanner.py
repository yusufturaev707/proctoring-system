"""
Masofaviy boshqaruv, virtualizatsiya va yordamchi vositalarni topish
va neytrallashtirish.

`app_closer.py` dan FARQI HAL QILUVCHI va ikkalasi ham kerak:

    app_closer      -> "ko'rinadigan OYNASI bor har qanday dastur"
                       Mezon — oyna. Nima ekani muhim emas.
    threat_scanner  -> "aynan SHU dastur, oynasi bo'lmasa ham"
                       Mezon — dasturning kimligi. Oyna muhim emas.

Aynan shu sababdan birinchisi ikkinchisini almashtira olmaydi:
AnyDesk xizmati, VBoxSVC yoki `remoting_host.exe` ning KO'RINADIGAN
OYNASI YO'Q va `app_closer` ularni umuman ko'rmaydi. Teskarisi ham
to'g'ri — katalogda yo'q messenjerni faqat `app_closer` yopadi.

NOM BO'YICHA QIDIRMAYMIZ (`process_identity.py` docstring'i): qaror
PE resursi, Authenticode imzosi, xizmat nomi va tinglanayotgan port
bo'yicha qabul qilinadi. `AnyDesk.exe` ni qayta nomlash bularning
hech biriga ta'sir qilmaydi.

UCHTA MANBA, BITTA HISOBOT:

    jarayonlar   -> `psutil.process_iter` + `process_identity`
    xizmatlar    -> `psutil.win_service_iter`, binar ham tekshiriladi
    portlar      -> tinglanayotgan TCP portlar (resursi va imzosi
                    butunlay tozalangan binar uchun oxirgi tor)

va ulardan TASHQARI ikkita muhit savoli: mashinaning o'zi virtual
mashinami (`host_virtualization`) va client masofaviy seansda
ishlayaptimi (`in_remote_session`). Ikkalasini ham "o'ldirib"
bo'lmaydi — ular hisobotga TO'SIQ sifatida tushadi.

XIZMATNI TO'XTATMASDAN JARAYONNI O'LDIRISH FOYDASIZ. AnyDesk,
TeamViewer va RustDesk xizmat sifatida o'rnatiladi va Windows SCM
o'ldirilgan jarayonni bir necha soniyada QAYTA KO'TARADI. Shuning
uchun tartib qat'iy: avval XIZMAT to'xtatiladi, keyin qolgan
jarayonlar o'ldiriladi. Teskari tartibda tozalash jimgina bekor
bo'lardi va hisobotda "hammasi yopildi" deb yozilardi.

ADMIN HUQUQI YO'Q BO'LSA TOZALASH YARIM QOLADI va bu KUTILGAN holat:
xizmatlarni to'xtatish ham, boshqa hisob jarayonini o'ldirish ham
administrator huquqini talab qiladi. Bunday holatda modul HECH
NARSANI yashirmaydi — topilgan, lekin yo'q qilinmagan tahdid
hisobotda `survivors` bo'lib qoladi va u imtihonni TO'SADI. "Topdim,
lekin qo'limdan kelmadi" holatini jimgina o'tkazib yuborish
tekshiruvning o'zini bekor qilardi.

KERNEL DARAJASIDA O'LDIRISH BU YERDA YO'Q va bo'lishi ham mumkin
emas. Buning uchun imzolangan kernel-mode drayver kerak; u Defender
uchun zararli xulq bo'lib ko'rinadi, PPL-himoyalangan jarayonga
baribir tegmaydi va ishlab turgan gipervizor drayverini majburan
tushirish BSOD beradi. Shuning uchun chegara ochiq: userland'da
o'ldirib bo'lmaydigan narsa O'LDIRILMAYDI, balki IMTIHONNI TO'SADI —
natija xuddi shunday qat'iy, lekin mashina ishlab turadi.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field

from services import threat_rules
from services.process_identity import (
    BinaryIdentity,
    foreign_rdp_sessions,
    host_virtualization,
    identity,
    in_remote_session,
    logoff_session,
    is_elevated,
)

log = logging.getLogger(__name__)

#: `WM_CLOSE` yuborilmaydi — bu yerda muloyimlikning ma'nosi yo'q.
#:
#: `app_closer` da u bor, chunki u FOYDALANUVCHI hujjatini ochiq
#: dasturni yopadi va saqlashga imkon berish kerak. Bu yerda esa
#: nishon — masofaviy boshqaruv agenti: unda saqlanadigan narsa yo'q,
#: "yopasizmi?" dialogi esa uni tirik qoldirardi.
_KILL_TIMEOUT = 3.0

#: Xizmat to'xtashini kutish (soniya).
_SERVICE_STOP_TIMEOUT = 8.0

#: Portlar bo'yicha qidiruvda e'tiborsiz qoldiriladigan jarayonlar.
#: Tizim binarlari (`svchost`) begona portni tinglayotgan bo'lsa ham
#: uni o'ldirish mashinani buzadi.
_NEVER_KILL = frozenset(
    {
        # --- Yadro va seans ---
        "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
        "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe",
        "svchost.exe", "fontdrvhost.exe", "memory compression",
        "audiodg.exe", "spoolsv.exe", "logonui.exe", "wudfhost.exe",
        # --- Qobiq ---
        #
        # `app_closer._PROTECTED` bilan ataylab takrorlanadi: ikkala
        # tozalovchi mustaqil ishlaydi va biridagi ro'yxatga tayanish
        # ikkinchisini qoidasiz qoldirardi. `applicationframehost.exe`
        # ayniqsa muhim - u BARCHA UWP oynalarini ushlab turadi va uni
        # o'ldirish ularni birdan yopadi.
        "dwm.exe", "explorer.exe", "sihost.exe", "ctfmon.exe",
        "textinputhost.exe", "applicationframehost.exe",
        "shellexperiencehost.exe", "startmenuexperiencehost.exe",
        "runtimebroker.exe", "taskhostw.exe", "dllhost.exe", "conhost.exe",
    }
)


# --------------------------------------------------------------------------
@dataclass
class Finding:
    """Bitta topilma."""

    code: str
    label: str
    category: str
    blocking: bool
    #: `process` | `service` | `session` | `host` | `rdp_session`
    kind: str
    #: Nima aynan mos kelgani — jurnal va panel uchun.
    evidence: str = ""
    pid: int = 0
    name: str = ""
    service: str = ""
    #: Yo'q qilindimi. `False` + `blocking` = imtihon to'siladi.
    neutralized: bool = False
    #: Yo'q qilinmagan bo'lsa — nega.
    reason: str = ""
    hint: str = ""
    #: `rdp_session` uchun: Windows seans raqami (`WTSLogoffSession`).
    session_id: int = 0

    @property
    def event_type(self) -> str:
        return threat_rules.EVENT_BY_CATEGORY.get(self.category, "process_blacklisted")

    def describe(self) -> str:
        bits = [self.label]
        if self.name:
            bits.append("({})".format(self.name))
        if self.service:
            bits.append("[xizmat: {}]".format(self.service))
        if self.evidence:
            bits.append("— {}".format(self.evidence))
        return " ".join(bits)


@dataclass
class ThreatReport:
    """Skanerlash natijasi."""

    findings: list = field(default_factory=list)
    scanned_processes: int = 0
    scanned_services: int = 0
    elevated: bool = False
    duration_ms: int = 0
    #: Skanerlash umuman bajarildimi (Windows emas, psutil yo'q...).
    supported: bool = True

    @property
    def survivors(self) -> list:
        """Yo'q qilinmagan TO'SIQ topilmalari — imtihon shular tufayli to'xtaydi."""
        return [item for item in self.findings if item.blocking and not item.neutralized]

    @property
    def neutralized(self) -> list:
        return [item for item in self.findings if item.neutralized]

    @property
    def warnings(self) -> list:
        """To'smaydigan, lekin operator bilishi kerak bo'lgan topilmalar."""
        return [item for item in self.findings if not item.blocking and not item.neutralized]

    def events(self) -> list:
        """
        Hodisa oqimiga tushadigan yozuvlar: `(tur, jiddiylik, payload)`.

        Faqat YO'Q QILINMAGANLAR uchun emas — yo'q qilinganlar ham
        yoziladi va bu ataylab. "AnyDesk topildi va yopildi" yozuvi
        bayonnomaning qismi: mashinada masofaviy boshqaruv o'rnatilgan
        ekani tekshiruv komissiyasi uchun ma'lumot bo'lib qoladi,
        garchi u imtihonga ta'sir qilmagan bo'lsa ham.
        """
        result = []
        for item in self.findings:
            # Yo'q qilingani — YUQORI, qolgani — KRITIK. Kritik hodisa
            # write-behind buferini chetlab o'tib darhol yoziladi
            # (`ingest.IMMEDIATE_SEVERITY`) va proktor ekranida o'sha
            # zahoti ko'rinadi.
            severity = 3 if item.neutralized else (4 if item.blocking else 2)
            result.append(
                (
                    item.event_type,
                    severity,
                    {
                        "codes": [item.code],
                        "label": item.label,
                        "process": item.name,
                        "service": item.service,
                        "evidence": item.evidence,
                        "neutralized": item.neutralized,
                        # `kind` ATAYLAB YUBORILMAYDI: frontendda u
                        # `client_anomaly` uchun band (`ANOMALY_KIND`)
                        # va "process" degan qiymat u yerda xom
                        # ko'rinishda chiqib qolardi.
                        "reason": item.reason,
                    },
                )
            )
        return result

    def summary(self) -> str:
        if not self.findings:
            return "tahdid topilmadi"
        return "{} topildi, {} yo'q qilindi, {} qoldi".format(
            len(self.findings), len(self.neutralized), len(self.survivors)
        )


# --------------------------------------------------------------------------
# Moslik
# --------------------------------------------------------------------------
def _matches(info: BinaryIdentity, filename: str, rule) -> str:
    """
    Qoida shu binarga mos keladimi. Qaytadi: DALIL satri yoki bo'sh satr.

    Tartib ishonchlilik bo'yicha: imzo -> `OriginalFilename` ->
    mahsulot nomi -> fayl nomi. Birinchi mos kelgan dalil qaytadi va
    aynan u jurnalga hamda panelga tushadi — operator "nega bu dastur
    yopildi?" degan savolga javob topa olishi kerak.
    """
    signer = (info.signer or "").lower()
    if signer:
        for needle in rule.publishers:
            if needle in signer:
                return "imzo: {}".format(info.signer)

    original = (info.original_filename or "").lower()
    if original:
        for needle in rule.originals:
            if original == needle:
                # ENG QIZIQ HOLAT: diskdagi nom boshqa bo'lsa, demak
                # fayl ataylab qayta nomlangan.
                if filename and filename != original:
                    return "qayta nomlangan: {} -> {}".format(info.original_filename, filename)
                return "OriginalFilename: {}".format(info.original_filename)

    haystack = info.haystack
    if haystack:
        for needle in rule.products:
            if needle in haystack:
                return "mahsulot: {}".format(info.product or info.description or needle)

    if filename:
        for needle in rule.names:
            if filename == needle:
                return "fayl nomi: {}".format(filename)
    return ""


def _match_rule(info: BinaryIdentity, filename: str, rules) -> tuple:
    """Birinchi mos kelgan qoida va dalil. Tartib MUHIM — aniq qoidalar oldinda."""
    for rule in rules:
        evidence = _matches(info, filename, rule)
        if evidence:
            return rule, evidence
    return None, ""


def _needs_signature(path: str) -> bool:
    """
    Imzoni o'qish shu fayl uchun arzimaydimi.

    `%SystemRoot%` ichidagi binarlar Microsoft tomonidan imzolangan va
    katalogdagi hech bir `publishers` ga mos kelmaydi — ularni
    tekshirish har skanerda bir necha yuz millisekund bekor yo'qotish
    bo'lardi. Tizim katalogidagi nishon (`mstsc.exe`) esa baribir
    `OriginalFilename` bilan tutiladi.
    """
    if not path:
        return False
    system_root = (os.environ.get("SystemRoot") or "C:\\Windows").lower()
    return not path.lower().startswith(system_root)


# --------------------------------------------------------------------------
# Skanerlash
# --------------------------------------------------------------------------
def scan(*, rules=None, allow=(), allow_virtual_host: bool = False) -> ThreatReport:
    """
    Mashinani tekshiradi. HECH NARSANI o'zgartirmaydi.

    `allow` — e'tiborsiz qoldiriladigan qoida kodlari yoki jarayon
    nomlari (`.env` dan). Muassasaning o'z masofaviy yordam agenti
    shu yerga yoziladi.
    """
    started = time.monotonic()
    rules = tuple(rules if rules is not None else threat_rules.ALL_RULES)
    allow = {str(item).strip().lower() for item in allow if str(item).strip()}
    report = ThreatReport(elevated=is_elevated())

    if sys.platform != "win32":
        log.info("Tahdid skaneri faqat Windows'da ishlaydi")
        report.supported = False
        return report

    try:
        import psutil
    except ImportError:
        log.error("psutil yo'q — tahdid skaneri ishlamaydi")
        report.supported = False
        return report

    own = _own_pids(psutil)

    # --- 1. Xizmatlar. AVVAL ULAR: jarayonni o'ldirishdan oldin uni
    # qayta ko'taradigan xizmat to'xtatilishi kerak.
    _scan_services(report, rules, allow, psutil)

    # --- 2. Jarayonlar.
    port_owners = _listening_ports(psutil)
    _scan_processes(report, rules, allow, psutil, own, port_owners)

    # --- 3. Muhit savollari — jarayonlardan MUSTAQIL.
    if in_remote_session():
        report.findings.append(
            Finding(
                code="remote_session",
                label="Mashina masofadan boshqarilmoqda",
                category="remote",
                blocking=True,
                kind="session",
                evidence="Windows seansi masofaviy (SM_REMOTESESSION)",
                hint=(
                    "Imtihon mashinasida to'g'ridan-to'g'ri, klaviatura va "
                    "monitor orqali ishlash kerak. Masofaviy ulanishni uzing."
                ),
            )
        )

    # BEGONA RDP SEANSI - o'zimizniki emas, mashinadagi IKKINCHI faol
    # RDP seans (Windows Server / RDPWrap; `mstsc /shadow` bilan
    # talabgor ekranini ko'rish). `SM_REMOTESESSION` uni ko'rmaydi.
    # `rdp_foreign_session` ni `.env` `THREAT_SCAN_ALLOW` ga yozish -
    # muassasa terminal serverida ishlasa.
    if "rdp_foreign_session" not in allow:
        for session in foreign_rdp_sessions():
            report.findings.append(
                Finding(
                    code="rdp_foreign_session",
                    label="Mashinaga boshqa RDP seansi ulangan",
                    category="remote",
                    blocking=True,
                    kind="rdp_session",
                    session_id=session.session_id,
                    # `name` - hodisa kaliti (`device_watch._seen`) ham:
                    # har seans alohida qayd etiladi.
                    name="RDP seans #{}".format(session.session_id),
                    evidence=session.describe(),
                    hint=(
                        "Mashinaga masofadan boshqa foydalanuvchi ulangan va u "
                        "ekranni kuzatishi mumkin. Seansni yoping (Task Manager "
                        "-> Users yoki `logoff <ID>`)."
                    ),
                )
            )

    marker = host_virtualization()
    if marker and "virtual_machine_host" not in allow:
        report.findings.append(
            Finding(
                code="virtual_machine_host",
                label="Client virtual mashina ichida ishlayapti",
                category="vm",
                # VDI o'rnatishlarida bu NORMAL holat bo'lishi mumkin,
                # shuning uchun to'siqni `.env` dan yumshatsa bo'ladi.
                blocking=not allow_virtual_host,
                kind="host",
                evidence="BIOS: {}".format(marker),
                hint=(
                    "Kiosk rejimi va tezkor tugmalar bloki mehmon tizimdan "
                    "tashqariga chiqmaydi — imtihonni haqiqiy mashinada "
                    "o'tkazing."
                ),
            )
        )

    report.duration_ms = int((time.monotonic() - started) * 1000)
    return report


def _own_pids(psutil) -> set:
    """O'z jarayonimiz, bolalari va ota-onalari — hech qachon nishon emas."""
    pids = {os.getpid()}
    try:
        current = psutil.Process()
        pids.update(child.pid for child in current.children(recursive=True))
        parent = current.parent()
        while parent is not None:
            pids.add(parent.pid)
            parent = parent.parent()
    except Exception:
        log.debug("O'z jarayonlar daraxtini aniqlab bo'lmadi", exc_info=True)
    return pids


def _listening_ports(psutil) -> dict:
    """
    `{port: pid}` — tinglanayotgan TCP portlar.

    Bu qidiruvning OXIRGI tori: resursi ham, imzosi ham tozalangan
    binar faqat shu yerda tutiladi. Masofaviy boshqaruv dasturi
    baribir ulanishni kutishi kerak va port raqami protokolning
    qismi — uni o'zgartirish mijoz tomonini ham o'zgartirishni
    talab qiladi.

    Windows'da to'liq ro'yxat uchun administrator huquqi kerak.
    Huquq yo'q bo'lsa lug'at bo'sh qoladi va qolgan uchta belgi
    avvalgidek ishlaydi.
    """
    owners: dict = {}
    try:
        connections = psutil.net_connections(kind="inet")
    except Exception:
        log.debug("Portlarni o'qib bo'lmadi (huquq yetmasligi mumkin)", exc_info=True)
        return owners

    for connection in connections:
        try:
            if connection.status != psutil.CONN_LISTEN or not connection.pid:
                continue
            owners.setdefault(connection.laddr.port, connection.pid)
        except Exception:
            continue
    return owners


def _scan_processes(report, rules, allow, psutil, own, port_owners) -> None:
    """Jarayonlar bo'yicha qidiruv — ikki bosqichli (arzon, keyin imzo)."""
    port_rules = [(port, rule) for rule in rules for port in rule.ports]
    seen_pids = set()

    for process in psutil.process_iter(["pid", "name", "exe"]):
        info = process.info
        pid = info.get("pid") or 0
        report.scanned_processes += 1
        if pid in own or pid in seen_pids:
            continue

        filename = (info.get("name") or "").strip().lower()
        if filename in _NEVER_KILL or filename in allow:
            continue

        path = info.get("exe") or ""
        binary = identity(path)
        rule, evidence = _match_rule(binary, filename, rules)

        # Ikkinchi bosqich: arzon belgilar hech narsa aytmadi. Imzoni
        # AYNAN SHU YERDA o'qiymiz — barcha jarayonlar uchun emas.
        if rule is None and _needs_signature(path):
            binary = identity(path, with_signature=True)
            rule, evidence = _match_rule(binary, filename, rules)

        # Uchinchi bosqich: port. Binar butunlay anonim bo'lsa ham
        # tinglayotgan porti uni oshkor qiladi.
        if rule is None and port_owners:
            for port, candidate in port_rules:
                if port_owners.get(port) == pid:
                    rule = candidate
                    evidence = "tinglanayotgan port: {}".format(port)
                    break

        if rule is None or rule.code in allow:
            continue

        seen_pids.add(pid)
        report.findings.append(
            Finding(
                code=rule.code,
                label=rule.label,
                category=rule.category,
                blocking=rule.blocking,
                kind="process",
                evidence="{} | {}".format(evidence, binary.summary()),
                pid=pid,
                name=filename,
                hint=rule.hint,
            )
        )


def _scan_services(report, rules, allow, psutil) -> None:
    """
    Xizmatlar bo'yicha qidiruv.

    Nom bo'yicha ham, XIZMAT BINARI bo'yicha ham tekshiriladi: xizmatni
    `HelpSvc` deb qayta ro'yxatdan o'tkazish mumkin, lekin u ishga
    tushiradigan `.exe` baribir o'z resursini va imzosini saqlaydi.
    """
    try:
        services = list(psutil.win_service_iter())
    except Exception:
        # `win_service_iter` Windows'dan boshqa joyda yo'q va huquq
        # yetmasa ham yiqilishi mumkin — bu to'xtatuvchi xato emas.
        log.debug("Xizmatlar ro'yxatini o'qib bo'lmadi", exc_info=True)
        return

    for service in services:
        report.scanned_services += 1
        try:
            name = (service.name() or "").strip()
            if service.status() != "running":
                continue
            binary_path = service.binpath() or ""
        except Exception:
            continue

        lowered = name.lower()
        if lowered in allow:
            continue

        rule = None
        evidence = ""
        for candidate in rules:
            if lowered in candidate.services:
                rule, evidence = candidate, "xizmat nomi: {}".format(name)
                break

        if rule is None:
            executable = _service_executable(binary_path)
            if executable:
                binary = identity(executable, with_signature=_needs_signature(executable))
                rule, evidence = _match_rule(
                    binary, os.path.basename(executable).lower(), rules
                )
                if rule is not None:
                    evidence = "xizmat «{}» | {}".format(name, evidence)

        if rule is None or rule.code in allow:
            continue

        report.findings.append(
            Finding(
                code=rule.code,
                label=rule.label,
                category=rule.category,
                blocking=rule.blocking,
                kind="service",
                evidence=evidence,
                service=name,
                hint=rule.hint,
            )
        )


def _service_executable(binary_path: str) -> str:
    """
    Xizmat buyrug'idan `.exe` yo'lini ajratadi.

    Buyruq argumentlar bilan keladi (`"C:\\...\\svc.exe" -k netsvcs`) va
    qo'shtirnoqli ham, qo'shtirnoqsiz ham bo'lishi mumkin.
    """
    text = (binary_path or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 1 else ""
    lowered = text.lower()
    cut = lowered.find(".exe")
    return text[: cut + 4] if cut != -1 else text.split(" ")[0]


# --------------------------------------------------------------------------
# Neytrallashtirish
# --------------------------------------------------------------------------
def neutralize(report: ThreatReport, *, end_rdp_sessions: bool = False) -> ThreatReport:
    """
    Topilganlarni yo'q qiladi va hisobotni JOYIDA yangilaydi.

    Tartib qat'iy — avval xizmatlar, keyin jarayonlar. Teskari
    tartibda SCM o'ldirilgan jarayonni qayta ko'tarardi va tozalash
    jimgina bekor bo'lardi.

    BEGONA RDP SEANSI faqat `end_rdp_sessions=True` da yakunlanadi - ya'ni
    FAQAT IMTIHON DAVOMIDA (`device_watch`). Ishga tushishda va "Davom
    etish" da u faqat qayd etiladi va imtihonni TO'SADI: imtihondan
    tashqarida seansni o'ldirish texnikning masofaviy xizmat seansini
    uzib, uning ishini yo'qotardi - operator uni o'zi yopadi.
    """
    if not report.findings or not report.supported:
        return report

    for finding in report.findings:
        if finding.kind != "rdp_session":
            continue
        if not end_rdp_sessions:
            finding.reason = "imtihondan tashqarida seans uzilmaydi - operator yopishi kerak"
            continue
        ok, reason = logoff_session(finding.session_id)
        if ok:
            # Qayta tekshiruv: logoff asinxron, seans bir necha soniya
            # "Active" ko'rinishi mumkin - natija KEYINGI skanerda
            # tasdiqlanadi (`sweep` qayta skanerlaydi, `device_watch`
            # esa 15 s dan keyin qaytadan ko'radi).
            finding.neutralized = True
            log.warning("Begona RDP seansi yakunlandi: %s", finding.evidence)
        else:
            finding.reason = reason
            log.error("Begona RDP seansini yakunlab bo'lmadi (%s): %s", reason, finding.evidence)

    try:
        import psutil
    except ImportError:
        return report

    for finding in report.findings:
        if finding.kind == "service":
            _stop_service(finding)

    victims = []
    for finding in report.findings:
        if finding.kind != "process" or not finding.pid:
            continue
        try:
            process = psutil.Process(finding.pid)
        except psutil.NoSuchProcess:
            # Xizmat to'xtaganda jarayoni ham ketgan — bu MUVAFFAQIYAT.
            finding.neutralized = True
            continue
        except Exception as exc:
            finding.reason = str(exc)[:120]
            continue
        victims.append((finding, process))
        try:
            process.kill()
        except psutil.NoSuchProcess:
            finding.neutralized = True
        except psutil.AccessDenied:
            finding.reason = (
                "huquq yetmadi (administrator kerak)"
                if not report.elevated
                else "himoyalangan jarayon"
            )
        except Exception as exc:
            finding.reason = str(exc)[:120]

    if victims:
        psutil.wait_procs([process for _, process in victims], timeout=_KILL_TIMEOUT)
        for finding, process in victims:
            if finding.neutralized:
                continue
            try:
                # `is_running()` O'ZI YETARLI EMAS: o'ldirilgan jarayon
                # zombi holatida qolishi va `True` qaytarishi mumkin.
                finding.neutralized = not process.is_running() or process.status() == "zombie"
            except psutil.NoSuchProcess:
                finding.neutralized = True
            except Exception:
                finding.neutralized = False
            if not finding.neutralized and not finding.reason:
                finding.reason = "jarayon tugamadi"

    # Muhit topilmalarini (`session`, `host`) yo'q qilib bo'lmaydi —
    # ular hisobotda o'zgarishsiz qoladi va imtihonni to'sadi.
    for finding in report.findings:
        if finding.kind in ("session", "host") and not finding.reason:
            finding.reason = "dasturiy yo'l bilan bartaraf etib bo'lmaydi"

    return report


# --- Windows Service Control Manager (faqat ctypes) -----------------------
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_STOP = 0x0020
_SERVICE_QUERY_STATUS = 0x0004
_SERVICE_CONTROL_STOP = 0x00000001
_SERVICE_STOPPED = 0x00000001


def _stop_service(finding: Finding) -> None:
    """
    Xizmatni to'xtatadi. Huquq yetmasa — sababni hisobotga yozadi.

    `sc.exe stop` ATAYLAB ishlatilmaydi: u alohida konsol jarayoni
    ochadi (kiosk oynasi ustida qora oyna miltillaydi), natijani
    faqat chiqish kodidan bilish mumkin va lokalizatsiyalangan
    Windows'da xato matni o'zgarib turadi.
    """
    if sys.platform != "win32" or not finding.service:
        return

    import ctypes
    from ctypes import wintypes

    class SERVICE_STATUS(ctypes.Structure):
        _fields_ = [
            ("dwServiceType", wintypes.DWORD),
            ("dwCurrentState", wintypes.DWORD),
            ("dwControlsAccepted", wintypes.DWORD),
            ("dwWin32ExitCode", wintypes.DWORD),
            ("dwServiceSpecificExitCode", wintypes.DWORD),
            ("dwCheckPoint", wintypes.DWORD),
            ("dwWaitHint", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    # `argtypes` MAJBURIY, faqat `restype` YETARLI EMAS. Usiz ctypes
    # Python butun sonini C `int` (32 bit) deb uzatadi, SCM deskriptori
    # esa 64-bit tizimda undan katta bo'ladi va chaqiruv
    # `OverflowError: int too long to convert` bilan yiqiladi. Bu
    # BARCHA xizmatlar uchun yiqilardi, ya'ni tozalashning butun
    # xizmat qismi jimgina ishlamasdi.
    status_pointer = ctypes.c_void_p
    advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.ControlService.argtypes = [wintypes.HANDLE, wintypes.DWORD, status_pointer]
    advapi32.ControlService.restype = wintypes.BOOL
    advapi32.QueryServiceStatus.argtypes = [wintypes.HANDLE, status_pointer]
    advapi32.QueryServiceStatus.restype = wintypes.BOOL
    advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    advapi32.CloseServiceHandle.restype = wintypes.BOOL

    manager = advapi32.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        finding.reason = "SCM ochilmadi (administrator kerak)"
        return

    handle = None
    try:
        handle = advapi32.OpenServiceW(
            manager, finding.service, _SERVICE_STOP | _SERVICE_QUERY_STATUS
        )
        if not handle:
            code = ctypes.get_last_error()
            # 5 = ERROR_ACCESS_DENIED. Eng ko'p uchraydigan holat va
            # operator uchun tushunarli matn bo'lishi kerak.
            finding.reason = (
                "xizmatni to'xtatish uchun administrator huquqi kerak"
                if code == 5
                else "xizmat ochilmadi (xato {})".format(code)
            )
            return

        status = SERVICE_STATUS()
        if not advapi32.ControlService(handle, _SERVICE_CONTROL_STOP, ctypes.byref(status)):
            code = ctypes.get_last_error()
            # 1051/1052 — boshqa xizmatlar shunga bog'liq yoki
            # to'xtatishni qabul qilmaydi.
            finding.reason = "xizmat to'xtamadi (xato {})".format(code)
            return

        deadline = time.monotonic() + _SERVICE_STOP_TIMEOUT
        while time.monotonic() < deadline:
            if not advapi32.QueryServiceStatus(handle, ctypes.byref(status)):
                break
            if status.dwCurrentState == _SERVICE_STOPPED:
                finding.neutralized = True
                return
            time.sleep(0.25)
        finding.reason = "xizmat belgilangan vaqtda to'xtamadi"
    finally:
        try:
            if handle:
                advapi32.CloseServiceHandle(handle)
            advapi32.CloseServiceHandle(manager)
        except Exception:
            log.debug("SCM deskriptorlarini yopishda xato", exc_info=True)


# --------------------------------------------------------------------------
def sweep(*, allow=(), allow_virtual_host: bool = False, dry_run: bool = False) -> ThreatReport:
    """
    To'liq sikl: topish -> yo'q qilish -> QAYTA TEKSHIRISH.

    Uchinchi qadam SHART va u eng muhimi. Xizmat to'xtatilgani
    jarayonning ham ketganini ANGLATMAYDI, o'ldirilgan agent esa
    o'zini qayta ko'taruvchi vazifa (Task Scheduler) orqali bir
    necha soniyada qaytishi mumkin. Faqat birinchi hisobotga tayanib
    "toza" deb xulosa qilish aynan shu holatlarni o'tkazib yuborardi.

    Qayta tekshiruvda topilgan narsa YO'Q QILINMAGAN deb belgilanadi:
    uni ikkinchi marta o'ldirishga urinish cheksiz tsikl bo'lardi va
    qayta ko'tarilayotgan agent bu tsikldan doim g'olib chiqardi.
    """
    report = scan(allow=allow, allow_virtual_host=allow_virtual_host)
    if dry_run or not report.findings:
        return report

    neutralize(report)

    rescan = scan(allow=allow, allow_virtual_host=allow_virtual_host)
    still_here = {
        (item.code, item.kind, item.name, item.service) for item in rescan.findings
    }
    for finding in report.findings:
        key = (finding.code, finding.kind, finding.name, finding.service)
        if key in still_here and finding.neutralized:
            finding.neutralized = False
            finding.reason = finding.reason or "yo'q qilingandan keyin qayta paydo bo'ldi"

    # Qayta skanerlashda YANGI topilma bo'lishi mumkin: xizmat
    # to'xtaganda uning jarayoni boshqa nom bilan qayta ko'tarilgan
    # bo'lishi mumkin. Ular ham hisobotga tushadi.
    known = {(item.code, item.kind, item.name, item.service) for item in report.findings}
    for finding in rescan.findings:
        key = (finding.code, finding.kind, finding.name, finding.service)
        if key not in known:
            finding.reason = "tozalashdan keyin paydo bo'ldi"
            report.findings.append(finding)

    report.duration_ms += rescan.duration_ms
    return report


# --------------------------------------------------------------------------
# Ishga tushishdagi hisobot
# --------------------------------------------------------------------------
#
# Skanerlash Qt YARATILISHIDAN OLDIN bajariladi (`main._sweep_threats`),
# ya'ni natijani `AppState` ga yozib bo'lmaydi - u hali mavjud emas.
# Naqsh `hardware_probe.prefetch()` dan olingan: natija modul
# darajasida yotadi va uni kerak bo'lgan sahifa o'qib oladi.
_LAST_REPORT: ThreatReport | None = None


def remember(report: ThreatReport | None) -> None:
    """
    Hisobotni saqlaydi. `None` — bir marta o'qilgandan keyin tozalash.

    Tozalash KERAK: hodisalar sessiyaga bog'langan va sessiya qayta
    boshlansa (operator kamerani tuzatib qayta urdi) o'sha eski
    topilmalar ikkinchi marta yozilardi.
    """
    global _LAST_REPORT
    _LAST_REPORT = report


def last_report() -> ThreatReport | None:
    """Oxirgi hisobot. Skaner o'chirilgan yoki ishlamagan bo'lsa — `None`."""
    return _LAST_REPORT
