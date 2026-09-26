"""
Imtihonga xalaqit beradigan dasturlar KATALOGI.

Bu fayl FAQAT MA'LUMOT: qidiruv mantig'i `threat_scanner.py` da,
jarayonni tanib olish esa `process_identity.py` da. Ajratishning sababi
oddiy — katalog tez-tez o'zgaradi (yangi masofaviy boshqaruv dasturi
har oyda chiqadi), mantiq esa deyarli hech qachon. Ularni bitta faylga
qo'shish har yangi nom uchun kodga tegishni talab qilardi.

NOMGA TAYANMAYMIZ va butun gap shunda. `AnyDesk.exe` ni `notepad.exe`
deb qayta nomlash bir soniyalik ish, ya'ni fayl nomi bo'yicha qidiruv
eng sodda chetlab o'tishga ham dosh bermaydi. Shuning uchun har bir
qoida BIR NECHTA belgi beradi va ular ishonchlilik bo'yicha shunday
joylashgan:

    publishers  -> Authenticode IMZOSIDAGI egasining nomi.
                   Faylni qayta nomlash imzoni o'zgartirmaydi; imzoni
                   buzish esa uni imzosiz holga keltiradi va bu o'zi
                   alohida belgi bo'lib qoladi (port + imzosiz binar).
    originals   -> PE resursidagi `OriginalFilename`. U kompilyatsiya
                   paytida yoziladi va faylni qayta nomlash unga
                   TEGMAYDI. Eng arzon va eng kuchli belgi.
    products    -> `ProductName` / `FileDescription` / `InternalName` /
                   `CompanyName`. Qism satr bo'yicha qidiriladi.
    services    -> Windows XIZMATI nomi. Oynasiz ishlaydigan qism
                   aynan shu yerda yashaydi va jarayonni o'ldirish uni
                   to'xtatmaydi — xizmat uni qayta ko'taradi.
    ports       -> tinglanayotgan TCP port. Qoidaning oxirgi tori:
                   ikkala PE maydoni ham tozalangan va imzo ham olib
                   tashlangan binar shu yerda tutiladi.
    names       -> fayl nomi. ZAXIRA va ataylab OXIRGI: u faqat
                   yuqoridagilarning hammasi bo'sh bo'lganda ishlaydi
                   (portativ, resurssiz binar).

KENG VENDOR IMZOSI RO'YXATGA KIRMAYDI. "Google LLC" ni `publishers` ga
yozish Chrome'ning o'zini ham, Google Update'ni ham tutardi;
"Microsoft Corporation" esa yarim tizimni. Shuning uchun Chrome Remote
Desktop `originals` va `products` bilan tutiladi — ular baribir qayta
nomlashdan himoyalangan.

`blocking` MAYDONI ALOHIDA va u `category` dan KELIB CHIQMAYDI. Aniq
vendor qoidasi (AnyDesk, VirtualBox) — to'siq: noto'g'ri ishlash
ehtimoli deyarli nol. Kalit so'z bo'yicha qidiradigan evristik qoida
(`generic_remote`) esa to'sMAYDI: "Remote" so'zi muassasaning o'z IT
yordam dasturida ham bo'lishi mumkin va u butun imtihonni bloklab
qo'ymasligi kerak. Dastur baribir o'ldiriladi va hodisa yoziladi —
farq faqat imtihon to'xtaydimi yoki yo'qmi.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Hodisa turlari — `ProctoringEvent.Type` bilan AYNAN mos bo'lishi shart.
#: Backend ro'yxatda yo'q turni rad etadi (serializer `ChoiceField`).
EVENT_BY_CATEGORY = {
    "remote": "rdp_detected",
    "vm": "vm_detected",
    "tool": "process_blacklisted",
}


@dataclass(frozen=True)
class ThreatRule:
    """
    Bitta dastur oilasi.

    Maydonlarning HAMMASI ixtiyoriy: portativ dasturda resurs
    bo'lmasligi, xizmatsiz dasturda `services` bo'sh bo'lishi mumkin.
    Mos kelish uchun BITTA belgi yetadi — ular alternativa, shart emas.
    """

    code: str
    label: str
    #: `remote` | `vm` | `tool`
    category: str
    #: Topilgani imtihonni to'sadimi.
    blocking: bool = True
    publishers: tuple = ()
    originals: tuple = ()
    products: tuple = ()
    names: tuple = ()
    services: tuple = ()
    ports: tuple = ()
    #: Operatorga ko'rsatiladigan izoh — nima qilish kerakligini aytadi.
    hint: str = ""

    @property
    def event_type(self) -> str:
        return EVENT_BY_CATEGORY.get(self.category, "process_blacklisted")


# --------------------------------------------------------------------------
# Masofaviy boshqaruv
# --------------------------------------------------------------------------
#
# Bu toifa imtihon uchun eng xavflisi: ekranni boshqa odam ko'radi va
# klaviaturani boshqarishi mumkin. Kamera hech narsa ko'rsatmaydi —
# talabgor ekranga qarab jim o'tiraveradi.
_REMOTE = (
    ThreatRule(
        code="anydesk",
        label="AnyDesk",
        category="remote",
        publishers=("anydesk software",),
        originals=("anydesk.exe",),
        products=("anydesk",),
        services=("anydesk",),
        ports=(7070,),
        hint="AnyDesk ni butunlay o'chiring (Dasturlarni o'chirish).",
    ),
    ThreatRule(
        code="teamviewer",
        label="TeamViewer",
        category="remote",
        publishers=("teamviewer",),
        originals=("teamviewer.exe", "teamviewer_service.exe", "tv_w32.exe", "tv_x64.exe"),
        products=("teamviewer",),
        services=("teamviewer",),
        ports=(5938,),
        hint="TeamViewer xizmatini to'xtating va dasturni o'chiring.",
    ),
    ThreatRule(
        code="rustdesk",
        label="RustDesk",
        category="remote",
        # RustDesk binarlari "Purslane Ltd" nomi bilan imzolanadi — u
        # dastur nomiga umuman o'xshamaydi va aynan shu sababdan bu
        # dasturni faqat fayl nomi bo'yicha qidirish ishlamaydi.
        publishers=("purslane", "rustdesk"),
        originals=("rustdesk.exe",),
        products=("rustdesk",),
        services=("rustdesk",),
        ports=(21115, 21116, 21117, 21118, 21119),
        hint="RustDesk xizmatini to'xtating va dasturni o'chiring.",
    ),
    ThreatRule(
        code="chrome_remote_desktop",
        label="Chrome Remote Desktop",
        category="remote",
        # "Google LLC" imzosi ATAYLAB yo'q: u Chrome'ning o'zini ham,
        # Google Update'ni ham tutardi. Resurs maydonlari esa faqat shu
        # mahsulotga tegishli va qayta nomlashdan himoyalangan.
        originals=(
            "remoting_host.exe",
            "remote_assistance_host.exe",
            "remoting_native_messaging_host.exe",
            "remoting_desktop.exe",
            "remoting_start_host.exe",
        ),
        products=("chrome remote desktop", "chromoting"),
        services=("chromoting",),
        hint="Chrome Remote Desktop Host ni dasturlar ro'yxatidan o'chiring.",
    ),
    ThreatRule(
        code="vnc",
        label="VNC (RealVNC / TightVNC / UltraVNC)",
        category="remote",
        publishers=("realvnc", "tightvnc", "glavsoft", "uvnc"),
        originals=(
            "vncserver.exe", "winvnc.exe", "winvnc4.exe", "tvnserver.exe",
            "vncviewer.exe", "uvnc_service.exe",
        ),
        products=("realvnc", "tightvnc", "ultravnc", "tigervnc", "vnc server"),
        services=("vncserver", "tvnserver", "uvnc_service", "winvnc"),
        ports=(5900, 5800),
        hint="VNC serverini to'xtating va xizmatini o'chiring.",
    ),
    ThreatRule(
        code="ammyy",
        label="Ammyy Admin",
        category="remote",
        originals=("aa_v3.exe", "ammyy_admin.exe"),
        products=("ammyy",),
        services=("ammyy",),
        hint="Ammyy Admin ni o'chiring.",
    ),
    ThreatRule(
        code="radmin",
        label="Radmin",
        category="remote",
        publishers=("famatech",),
        originals=("rserver3.exe", "radmin.exe", "rserver.exe"),
        products=("radmin",),
        services=("rserver3", "radmin"),
        ports=(4899,),
        hint="Radmin Server xizmatini to'xtating.",
    ),
    ThreatRule(
        code="supremo",
        label="Supremo",
        category="remote",
        publishers=("nanosystems",),
        originals=("supremo.exe", "supremosystem.exe"),
        products=("supremo",),
        services=("supremosystem",),
        hint="Supremo ni o'chiring.",
    ),
    ThreatRule(
        code="ultraviewer",
        label="UltraViewer",
        category="remote",
        publishers=("ducfabulous", "ultraviewer"),
        originals=("ultraviewer_desktop.exe", "ultraviewer_service.exe"),
        products=("ultraviewer",),
        services=("ultraviewer_service",),
        hint="UltraViewer ni o'chiring.",
    ),
    ThreatRule(
        code="litemanager",
        label="LiteManager",
        category="remote",
        originals=("romserver.exe", "romviewer.exe", "romfusionserv.exe"),
        products=("litemanager", "remote office manager"),
        services=("romserver", "romservice"),
        hint="LiteManager serverini o'chiring.",
    ),
    ThreatRule(
        code="splashtop",
        label="Splashtop",
        category="remote",
        publishers=("splashtop",),
        originals=("srserver.exe", "srservice.exe", "splashtopstreamer.exe", "sragent.exe"),
        products=("splashtop",),
        services=("ssubagent", "splashtopremoteservice", "srservice"),
        hint="Splashtop Streamer ni o'chiring.",
    ),
    ThreatRule(
        code="screenconnect",
        label="ScreenConnect / ConnectWise Control",
        category="remote",
        publishers=("connectwise", "screenconnect", "elsinore"),
        originals=("screenconnect.clientservice.exe", "connectwisecontrol.client.exe"),
        products=("screenconnect", "connectwise control"),
        services=("screenconnect",),
        hint="ScreenConnect client xizmatini o'chiring.",
    ),
    ThreatRule(
        code="logmein",
        label="LogMeIn / GoToMyPC",
        category="remote",
        publishers=("logmein", "goto technologies", "citrix online"),
        originals=("lmiguardiansvc.exe", "logmein.exe", "g2comm.exe", "g2svc.exe"),
        products=("logmein", "gotomypc"),
        services=("logmein", "lmiguardiansvc", "gotomypc"),
        hint="LogMeIn / GoToMyPC xizmatlarini o'chiring.",
    ),
    ThreatRule(
        code="zoho_assist",
        label="Zoho Assist",
        category="remote",
        publishers=("zoho",),
        originals=("zaservice.exe", "zohomeeting.exe", "za_access.exe"),
        products=("zoho assist",),
        services=("zohomeeting", "zaservice"),
        hint="Zoho Assist agentini o'chiring.",
    ),
    ThreatRule(
        code="nomachine",
        label="NoMachine",
        category="remote",
        publishers=("nomachine",),
        originals=("nxservice.exe", "nxplayer.exe", "nxd.exe"),
        products=("nomachine",),
        services=("nxservice",),
        ports=(4000,),
        hint="NoMachine serverini o'chiring.",
    ),
    ThreatRule(
        code="parsec",
        label="Parsec",
        category="remote",
        publishers=("parsec cloud",),
        originals=("parsecd.exe", "parsec.exe"),
        products=("parsec",),
        services=("parsec",),
        hint="Parsec ni o'chiring.",
    ),
    ThreatRule(
        code="remote_utilities",
        label="Remote Utilities",
        category="remote",
        publishers=("remote utilities",),
        originals=("rutserv.exe", "rfusclient.exe"),
        products=("remote utilities",),
        services=("rmanservice",),
        hint="Remote Utilities serverini o'chiring.",
    ),
    ThreatRule(
        code="dwservice",
        label="DWService",
        category="remote",
        originals=("dwagent.exe", "dwagsvc.exe"),
        products=("dwservice", "dwagent"),
        services=("dwagent",),
        hint="DWAgent xizmatini o'chiring.",
    ),
    ThreatRule(
        code="getscreen",
        label="Getscreen / HelpWire / Iperius Remote",
        category="remote",
        publishers=("getscreen", "iperius", "helpwire"),
        originals=("getscreen.exe", "iperiusremote.exe", "helpwire.exe"),
        products=("getscreen", "iperius remote", "helpwire"),
        hint="Masofaviy yordam dasturini o'chiring.",
    ),
    ThreatRule(
        code="mstsc",
        label="Remote Desktop Connection (mstsc)",
        category="remote",
        # `mstsc.exe` — Windows'ning O'ZINIKI va u har doim diskda
        # turadi. Signal "bor" emas, "ISHLAYAPTI": talabgor undan
        # boshqa mashinaga ulanib, testni o'sha yerda yechishi mumkin.
        originals=("mstsc.exe",),
        products=("remote desktop connection",),
        names=("mstsc.exe",),
        hint="Masofaviy ish stoli oynasini yoping.",
    ),
)


# --------------------------------------------------------------------------
# Virtualizatsiya va emulyatorlar
# --------------------------------------------------------------------------
#
# Virtual mashina ichida ikkinchi Windows ishlaydi va u bizning
# kuzatuvimiz uchun mavjud emas: skrinshot faqat o'z ekranini oladi,
# tezkor tugmalar bloki mehmon tizimga tegmaydi.
_VM = (
    ThreatRule(
        code="virtualbox",
        label="Oracle VirtualBox",
        category="vm",
        publishers=("innotek",),
        originals=(
            "virtualbox.exe", "virtualboxvm.exe", "vboxsvc.exe",
            "vboxheadless.exe", "vboxmanage.exe", "vboxsds.exe",
        ),
        products=("virtualbox",),
        services=("vboxsds",),
        hint="VirtualBox oynalarini va VBoxSVC xizmatini to'xtating.",
    ),
    ThreatRule(
        code="vmware",
        label="VMware Workstation / Player",
        category="vm",
        publishers=("vmware",),
        originals=(
            "vmware.exe", "vmware-vmx.exe", "vmplayer.exe",
            "vmware-tray.exe", "vmware-hostd.exe", "vmware-authd.exe",
        ),
        products=("vmware workstation", "vmware player", "vmware vmx"),
        services=("vmwarehostd", "vmauthdservice", "vmware nat service"),
        hint="VMware mashinalarini to'xtating.",
    ),
    ThreatRule(
        code="hyperv_console",
        label="Hyper-V mashinasi",
        category="vm",
        # `vmconnect.exe` — mehmon tizim OYNASI, ya'ni ishlab turgan
        # virtual mashinaning aniq belgisi.
        originals=("vmconnect.exe",),
        products=("hyper-v virtual machine connection",),
        hint="Hyper-V mashinasi oynasini yoping.",
    ),
    ThreatRule(
        code="hyperv_service",
        label="Hyper-V platformasi yoqilgan",
        category="vm",
        # TO'SMAYDI: `vmms`/`vmcompute` WSL2, Docker Desktop va Windows
        # Sandbox tomonidan ham ishlatiladi. Ularning borligi "virtual
        # mashina ishlayapti" degani EMAS, shuning uchun faqat qayd
        # etiladi. Xizmat ham to'xtatilmaydi — u WSL2 ni o'ldirardi.
        blocking=False,
        services=("vmms", "vmcompute"),
        hint="Hyper-V yoqilgan — imtihon mashinasida o'chirish tavsiya etiladi.",
    ),
    ThreatRule(
        code="qemu",
        label="QEMU / KVM",
        category="vm",
        originals=("qemu-system-x86_64.exe", "qemu-system-i386.exe", "qemu.exe"),
        products=("qemu",),
        hint="QEMU mashinasini to'xtating.",
    ),
    ThreatRule(
        code="parallels",
        label="Parallels",
        category="vm",
        publishers=("parallels",),
        originals=("prl_vm_app.exe", "prl_client_app.exe"),
        products=("parallels",),
        services=("prl_tools",),
        hint="Parallels mashinasini to'xtating.",
    ),
    ThreatRule(
        code="sandbox",
        label="Sandboxie / Windows Sandbox",
        category="vm",
        publishers=("sandboxie", "invincea"),
        originals=("sbiesvc.exe", "sbiectrl.exe", "windowssandbox.exe"),
        products=("sandboxie", "windows sandbox"),
        services=("sbiesvc",),
        hint="Sandbox muhitini yoping.",
    ),
    ThreatRule(
        code="android_emulator",
        label="Android emulyatori",
        category="vm",
        publishers=("bluestacks", "now.gg", "xuanzhi", "microvirt"),
        originals=(
            "hd-player.exe", "bluestacks.exe", "ldplayer.exe", "dnplayer.exe",
            "nox.exe", "noxvmhandle.exe", "memu.exe", "memuheadless.exe",
        ),
        products=("bluestacks", "ldplayer", "nox player", "memu", "android emulator"),
        services=("bstservice", "ldmutexservice"),
        hint="Android emulyatorini yoping.",
    ),
)


# --------------------------------------------------------------------------
# Yordamchi vositalar
# --------------------------------------------------------------------------
#
# Bu toifa to'sMAYDI: bular imtihonni mumkin bo'lmagan holga
# keltirmaydi, lekin dalilni buzadi (virtual kamera) yoki savolni
# tashqariga chiqaradi (ekran yozuvchi). Yopiladi va qayd etiladi.
_TOOLS = (
    ThreatRule(
        code="virtual_camera",
        label="Virtual kamera",
        category="tool",
        blocking=False,
        publishers=("manycam", "splitmedialabs"),
        originals=("obs64.exe", "obs32.exe", "manycam.exe", "xsplit.core.exe"),
        products=("obs studio", "manycam", "xsplit", "splitcam", "youcam"),
        hint=(
            "Virtual kamera dasturi oldindan yozilgan videoni jonli oqim "
            "sifatida ko'rsatishi mumkin — yoping."
        ),
    ),
    ThreatRule(
        code="screen_recorder",
        label="Ekran yozuvchi",
        category="tool",
        blocking=False,
        publishers=("bandicam", "techsmith"),
        originals=("bandicam.exe", "camtasia.exe", "camrec.exe", "sharex.exe"),
        products=("bandicam", "camtasia", "sharex", "screen recorder"),
        hint="Ekran yozish dasturi savollarni tashqariga chiqarishi mumkin.",
    ),
    ThreatRule(
        code="automation",
        label="Avtomatlashtirish vositasi",
        category="tool",
        blocking=False,
        publishers=("autohotkey",),
        originals=("autohotkey.exe", "autohotkeyu64.exe", "autoit3.exe"),
        products=("autohotkey", "autoit"),
        hint="Makros dasturi klaviatura blokini chetlab o'tishi mumkin.",
    ),
)


# --------------------------------------------------------------------------
# Kalit so'z tori — HAR DOIM ENG OXIRIDA
# --------------------------------------------------------------------------
#
# Bu qoidalar ALOHIDA ro'yxatda va sabab TARTIBDA. Qidiruv birinchi mos
# kelgan qoidada to'xtaydi, ya'ni "remote desktop" kabi keng kalit so'z
# undan keyin turgan har qanday ANIQ qoidani soyalab qo'yardi: panelga
# qo'shilgan "Remote Support Pro" yozuvi hech qachon ishlamasdi va
# hodisada uning nomi ham, toifasi ham ko'rinmasdi.
#
# Shuning uchun yakuniy tartib har doim:
#
#     aniq ichki qoidalar -> serverdagi qoidalar -> kalit so'z tori
#
FALLBACK_RULES = (
    ThreatRule(
        code="generic_remote",
        label="Masofaviy boshqaruv (nomi bo'yicha)",
        category="remote",
        # TO'SMAYDI. Kalit so'z tori keng va u muassasaning o'z IT
        # yordam agentini ham tutishi mumkin — bunday holatda butun
        # imtihonni bloklash noto'g'ri bo'lardi. Dastur baribir
        # yopiladi va hodisa yoziladi.
        blocking=False,
        products=(
            "remote desktop", "remote control", "remote access",
            "remote support", "remote assistance", "screen sharing",
        ),
        hint="Masofaviy kirish imkonini beradigan dastur — yopilganini tekshiring.",
    ),
)

#: Aniq qoidalar. Serverdagi ro'yxat BULARDAN KEYIN qo'shiladi.
BUILTIN_RULES = _REMOTE + _VM + _TOOLS

#: Serversiz kontekst uchun to'liq to'plam (ishga tushishdagi tozalash).
ALL_RULES = BUILTIN_RULES + FALLBACK_RULES


def by_code() -> dict:
    """`code -> ThreatRule`. Serverdan kelgan qoidalarni birlashtirishda kerak."""
    return {rule.code: rule for rule in ALL_RULES}
