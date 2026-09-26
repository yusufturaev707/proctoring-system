"""
Kiosk rejimi: tezkor tugmalarni bloklash va tizim yorliqlarini o'chirish.

OS darajasidagi barcha aralashuv SHU FAYLDA. Sabab oddiy: bu modul
foydalanuvchi mashinasining GLOBAL holatini o'zgartiradi (klaviatura
hook'i, registry kalitlari) va "kim nimani o'zgartirdi, kim qaytardi"
degan savolga bitta joydan javob berilishi kerak. Xom hook MEXANIZMI
(thread, tiriklik tekshiruvi, qayta o'rnatish) - `keyboard_hook.py`;
nima yutilishini hal qiladigan SIYOSAT - shu yerda.

Uch qatlam, har biri alohida ishlaydi:

  1. klaviatura hook'i - Alt+Tab, Win, PrintScreen kabi
     kombinatsiyalarni bosilishidan OLDIN yutadi;
  2. Windows Accessibility yorliqlari - Shift x5 (Sticky Keys),
     Shift 8s (Filter Keys), NumLock 5s (Toggle Keys). Bularni
     hook ushlay olmaydi: ular OS ichida, hook zanjiridan
     oldinroq ishlaydi va ekranga MODAL oyna chiqaradi - to'liq
     ekran rejimi shu zahoti buziladi;
  3. oyna darajasi - kiosk oynalarida Windows System Menu YO'Q
     (`kiosk_window_flags`, `install_system_menu_guard`). Hook
     global va uni Windows jimgina olib tashlashi mumkin
     (`LowLevelHooksTimeout`), shuning uchun "Space bosilganda
     tepada menyu chiqdi" holati faqat hook'ga ishonib qolmaydi.

MODIFIKATORLAR HECH QACHON USHLANMAYDI VA QAYTA YUBORILMAYDI.
Ilgari `keyboard` kutubxonasining `add_hotkey(..., suppress=True)`
ishlatilardi va kutubxona
kombinatsiyadagi har modifikatorni (Alt, Ctrl, Shift) bosilishida
USHLAB turib, keyin sun'iy `press()` bilan qayta yuborardi. O'lchangan
oqibatlari (`tests/test_lockdown_hook.py`):

  * Alt+Shift (til almashtirish) OS'ga `shift↓ shift↑ alt↓ alt↑`
    bo'lib yetardi - ikkalasi hech qachon birga bosilmagan, til
    almashmasdi;
  * kombinatsiya AYNAN mos kelishi kerak edi: `alt+space` bloklangan,
    `alt+shift+space` / `ctrl+alt+space` (AltGr) esa Space'ni Alt
    bosilgan oynaga o'tkazardi - va oyna System Menu ochardi. Til
    almashtirgan zahoti probel bosish - talabgorning oddiy harakati.

Endi faqat ASOSIY tugma (Tab, Space, F4...) yutiladi va faqat
kerakli modifikatorlar HAQIQATAN bosilgan bo'lsa (`GetAsyncKeyState`,
o'z hisobimiz emas - o'tkazib yuborilgan UP hodisasi uni "abadiy
bosilgan" qilib, oddiy probelni yutib qo'yardi). Ortiqcha modifikator
bloklashni BEKOR QILMAYDI. Tugmalar VIRTUAL-KEY bo'yicha tanlanadi,
skan-kod emas: `print screen` va `Num *` bir xil skan-kodli (55), VK
esa har xil (`VK_SNAPSHOT` / `VK_MULTIPLY`); VK - Chromium va Windows
yorliqlarni aynan qanday talqin qilsa, shunday.

YOPISHGAN MODIFIKATOR (`_tick`). Alt/Ctrl/Win `_STUCK_AFTER_S` dan
ortiq uzluksiz bosilgan va OS ham "bosilgan" desa - u MANTIQAN qo'yib
yuboriladi, keyingi auto-repeat'lari esa jismoniy UP kelguncha yutiladi.
Apparat nosozligi (yopishgan tugma) yoki yo'qolgan UP hodisasida Windows
Alt'ni doim bosilgan deb bilardi: har Space - Alt+Space, har harf -
menyu tezlatgichi, ya'ni talabgor umuman yoza olmasdi. Imtihonda
Alt'ni 20 soniya ushlab turishning ma'nosi yo'q, Shift esa uzoqroq
ushlanishi mumkin (katta harflar) - chegara undan uzunroq.

QAT'IY QOIDA: registry o'zgarishi dastur bilan birga o'lmaydi. Hook
jarayon tugashi bilan OS tomonidan olib tashlanadi, registry esa
QOLADI - talaba mashinasida Sticky Keys butunlay o'chgan holda. Shu
sababli tiklash uch joyga qo'yilgan: oddiy chiqish, `atexit` va
tutilmagan istisno. Referens loyihada faqat birinchisi bor edi.
"""

from __future__ import annotations

import atexit
import logging
import sys
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

from services.keyboard_hook import KeyboardHook

_KEYBOARD_AVAILABLE = sys.platform == "win32"


#: Panelda yozilgan kod -> `_NAMED_VKS` dagi kanonik nom.
#:
#: Kerak, chunki panelga kodni ODAM kiritadi va u tabiiy ravishda
#: "printscreen" deb yozadi. Noma'lum nom log'ga tushadi va o'sha kod
#: bloklanmaydi - nomlash farqi tufayli ekran nusxasi JIMGINA ochiq
#: qolishi mumkin emas.
_KEY_ALIASES = {
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


#: HECH QACHON bloklanmaydigan kombinatsiya.
#:
#: Ctrl+Q - dasturdan chiqishning yagona yo'li (login sahifasidan
#: boshlab). Uni panelga "bloklanadigan tugmalar" ro'yxatiga qo'shish
#: mumkin va shunda mashina o'zini qulflab qo'yardi: chiqish dialogini
#: ochib bo'lmaydi, Alt+F4 allaqachon bloklangan, `closeEvent` esa
#: parolsiz yopilishni rad etadi. Bu xatoni administrator o'zi ham
#: sezmasligi mumkin, shuning uchun qoida KODDA.
_NEVER_BLOCKED = frozenset({"ctrl+q"})


#: Modifikator nomi -> Windows virtual-key kodlari (birortasi bosilgan
#: bo'lsa yetarli). Holat `GetAsyncKeyState` dan o'qiladi: LL hook
#: ichida u JORIY hodisadan oldingi, ya'ni aynan kerakli holatni beradi.
_MODIFIER_VKS = {
    "alt": (0x12,), "left alt": (0xA4,), "right alt": (0xA5,), "alt gr": (0xA5,),
    "ctrl": (0x11,), "control": (0x11,), "left ctrl": (0xA2,), "right ctrl": (0xA3,),
    "shift": (0x10,), "left shift": (0xA0,), "right shift": (0xA1,),
    "win": (0x5B, 0x5C), "left windows": (0x5B,), "right windows": (0x5C,),
}

#: Modifikator ASOSIY tugma bo'lganda (`win`, yolg'iz `ctrl`) - hook
#: hodisasida keladigan TOMONLI kodlar. LL hook `VK_MENU` emas,
#: `VK_LMENU`/`VK_RMENU` beradi.
_MODIFIER_EVENT_VKS = {
    "alt": (0xA4, 0xA5, 0x12), "left alt": (0xA4,), "right alt": (0xA5,), "alt gr": (0xA5,),
    "ctrl": (0xA2, 0xA3, 0x11), "control": (0xA2, 0xA3, 0x11),
    "left ctrl": (0xA2,), "right ctrl": (0xA3,),
    "shift": (0xA0, 0xA1, 0x10), "left shift": (0xA0,), "right shift": (0xA1,),
    "win": (0x5B, 0x5C), "left windows": (0x5B,), "right windows": (0x5C,),
}

#: Nom -> virtual-key. Harf va raqamlar alohida (`_key_vks`). Tinish
#: belgilari US joylashuvidagi tugma bo'yicha (VK_OEM_*).
_NAMED_VKS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "pause": 0x13, "caps lock": 0x14,
    "esc": 0x1B, "space": 0x20, "page up": 0x21, "page down": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "print screen": 0x2C, "insert": 0x2D, "delete": 0x2E, "apps": 0x5D, "menu": 0x5D,
    "num *": 0x6A, "num +": 0x6B, "num -": 0x6D, "num .": 0x6E, "num /": 0x6F,
    "num lock": 0x90, "scroll lock": 0x91,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
_NAMED_VKS.update({"num {}".format(i): 0x60 + i for i in range(10)})
_NAMED_VKS.update({"f{}".format(i): 0x6F + i for i in range(1, 25)})

#: Yopishgan modifikator chegarasi (soniya) - TOMONLI VK bo'yicha.
#: Shift uzunroq: katta harflar yozilganda u qonuniy ushlab turiladi.
_STUCK_AFTER_S = {
    0xA4: 20.0, 0xA5: 20.0,   # Alt
    0xA2: 20.0, 0xA3: 20.0,   # Ctrl
    0x5B: 20.0, 0x5C: 20.0,   # Win
    0xA0: 60.0, 0xA1: 60.0,   # Shift
}
_VK_NAMES = {
    0xA4: "alt", 0xA5: "right alt", 0xA2: "ctrl", 0xA3: "right ctrl",
    0x5B: "win", 0x5C: "right win", 0xA0: "shift", 0xA1: "right shift",
}


def _key_vks(name: str) -> tuple:
    """Tugma nomi -> hook hodisasida keladigan VK'lar. Noma'lumda `ValueError`."""
    if name in _MODIFIER_EVENT_VKS:
        return _MODIFIER_EVENT_VKS[name]
    if name in _NAMED_VKS:
        return (_NAMED_VKS[name],)
    if len(name) == 1 and ("a" <= name <= "z" or "0" <= name <= "9"):
        # Harf VK'si joylashuvga bog'liq emas (kirill joylashuvida ham
        # I tugmasi VK_I) - Chromium'ning Ctrl+Shift+I ham shunga qaraydi.
        return (ord(name.upper()),)
    raise ValueError("noma'lum tugma: {!r}".format(name))


def _normalize(code: str) -> str:
    """`Ctrl + Shift+I` -> `ctrl+shift+i`, alias'lar bilan."""
    parts = [part.strip().lower() for part in str(code or "").split("+")]
    parts = [_KEY_ALIASES.get(part, part) for part in parts if part]
    return "+".join(parts)


class _Combo:
    """
    Bloklanadigan bitta kombinatsiya: ASOSIY tugma + talab qilingan
    modifikatorlar.

    Asosiy tugma - modifikator bo'lmagan yagona qism (`alt+tab` da Tab).
    Faqat modifikatordan iborat kod (`win`, `alt`) - o'sha tugmaning
    O'ZI har doim bloklanadi.
    """

    __slots__ = ("code", "vks", "required")

    def __init__(self, code: str, vks, required: tuple) -> None:
        self.code = code
        #: Asosiy tugmaning hook hodisasidagi VK'lari.
        self.vks = frozenset(vks)
        #: Har element - bitta modifikatorning VK variantlari.
        self.required = required


def _parse_combo(code: str, key_vks=_key_vks) -> _Combo:
    """`ctrl+shift+i` -> `_Combo`. Noma'lum tugmada `ValueError`."""
    parts = [part for part in code.split("+") if part]
    if len(set(parts)) != len(parts):
        raise ValueError("takrorlangan tugma")
    main = [part for part in parts if part not in _MODIFIER_VKS]
    if len(main) > 1:
        raise ValueError("bitta asosiy tugma bo'lishi kerak")
    key = main[0] if main else parts[-1]
    required = tuple(_MODIFIER_VKS[part] for part in parts if part != key)
    return _Combo(code, key_vks(key), required)


def _key_is_down(vk: int) -> bool:
    """Tugma HOZIR bosilganmi (asinxron holat, fokusdan qat'i nazar)."""
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def resolve_hotkeys(server: Optional[list], default: Optional[list]) -> list:
    """
    Qaysi ro'yxat qo'llanadi: serverniki yoki `.env` standarti.

    IKKI QATLAM. `.env` dagi `BLOCKED_HOTKEYS` dastur ishga tushishi
    bilan, preflight'dan OLDIN qo'llanadi - server javob bermasa ham
    mashina qulfsiz qolmasligi kerak. Server ro'yxati kelsa (preflight,
    handshake, imtihon profili) u standartni ALMASHTIRADI, ustiga
    qo'shilmaydi: bino yoki imtihon profilidan olib tashlangan tugma
    bloklangan holda qolib ketmasligi kerak (masalan chet tili
    imtihonida ruxsat etilgan kombinatsiya).

    BO'SH SERVER RO'YXATI = "ADMINISTRATOR SOZLAMAGAN", "hech narsani
    bloklama" EMAS. Uchta sabab:

      * server bo'sh ro'yxatni uch xil holatda beradi - profilda tugma
        tanlanmagan, faol `Setting` umuman yo'q (`_default_config`) va
        eski server (kalit yo'q) - va ularning HECH BIRI ongli qaror
        emas;
      * kiosk rejimida "hech narsa bloklanmasin" o'z-o'ziga zid: Alt+Tab
        va Win ochiq kiosk - kiosk emas. Bunday mashina kerak bo'lsa
        u `.env` da hal qilinadi (`KIOSK_MODE=false` yoki bo'sh
        `BLOCKED_HOTKEYS`), ya'ni ochiq va mashina darajasida;
      * xato narxi nosimmetrik: keraksiz bloklangan tugma operatorni
        noqulay qiladi, tasodifan ochilgan Alt+Tab esa imtihonni
        ochiq qoldiradi.

    `None` (kalit umuman kelmagan) ham xuddi shunday. Ro'yxat nusxasi
    qaytadi - chaqiruvchi uni o'zgartirsa `config` buzilmasligi kerak.
    """
    chosen = server if server else default
    return [code for code in (chosen or []) if str(code or "").strip()]


class KeyPolicy:
    """
    NIMA yutiladi - sof siyosat, OS'siz testlanadi.

    Ikki joyda BIR XIL ishlaydi: klaviatura qulfi jarayonida
    (`keyboard_hook_process`, asosiy yo'l) va zaxira sifatida client
    ichida. Natijalar callback orqali: `on_blocked(code)` - bloklangan
    urinish, `on_issue(reason, key)` - qulfning o'z nosozligi.
    `release_key` - yopishgan tugmani OS'da qo'yib yuboruvchi (hook).
    """

    def __init__(self, *, key_is_down=_key_is_down, clock=time.monotonic,
                 on_blocked=None, on_issue=None) -> None:
        #: Ko'p modifikatorli oldin: `alt+shift+tab` bosilganda observer
        #: `alt+tab` emas, aniqrog'ini olsin.
        self.combos: tuple = ()
        #: Yutilgan tugmalar (VK). Tugma o'z UP'igacha yutiladi: aks holda
        #: Alt qo'yib yuborilgach Tab'ning auto-repeat'i ekranga chiqib
        #: ketar, UP esa DOWN'siz OS'ga yetardi.
        self.swallowed: set = set()
        #: O'tkazilgan modifikator (tomonli VK) -> birinchi DOWN vaqti.
        self.down_since: dict = {}
        #: Yopishgan deb mantiqan qo'yib yuborilgan modifikatorlar.
        self.stuck: set = set()
        self.release_key = None
        self._key_is_down = key_is_down
        self._clock = clock
        self._on_blocked = on_blocked
        self._on_issue = on_issue

    @staticmethod
    def parse(keys) -> tuple:
        """Kodlar -> (`_Combo` lar, bloklangan kodlar, xatolar)."""
        combos, blocked, failed = [], [], []
        for raw in keys or []:
            code = _normalize(raw)
            if not code or code in blocked:
                continue
            if code in _NEVER_BLOCKED:
                log.warning(
                    "'%s' bloklanmaydi: u dasturdan chiqishning yagona "
                    "yo'li. Ro'yxatdan olib tashlang.", code
                )
                continue
            try:
                combos.append(_parse_combo(code))
            except Exception as exc:
                failed.append("{} ({})".format(code, str(exc)[:60]))
                continue
            blocked.append(code)
        return combos, blocked, failed

    def set_codes(self, keys) -> list:
        """Ro'yxatni ALMASHTIRADI (hook o'zgarishsiz), bloklanganini qaytaradi."""
        combos, blocked, failed = self.parse(keys)
        if failed:
            log.warning("Qulflash: bloklanmagan tugmalar: %s", failed)
        self.combos = tuple(sorted(combos, key=lambda c: -len(c.required)))
        return blocked

    def reset(self) -> None:
        self.combos = ()
        self.swallowed = set()
        self.down_since = {}
        self.stuck = set()

    def report(self, reason: str, key: str = "") -> None:
        if self._on_issue is None:
            return
        try:
            self._on_issue(reason, key)
        except Exception:
            log.debug("Qulflash nosozlik observer'i xatosi", exc_info=True)

    # ------------------------------------------------------------------
    def on_key(self, vk: int, down: bool, injected: bool = False) -> bool:
        """
        Har klaviatura hodisasi: `False` - yutish, `True` - o'tkazish.

        Hook thread'ida, OS kutib turgan paytda chaqiriladi: tez bo'lishi
        SHART. INJEKT qilingan hodisa ham xuddi shunday tekshiriladi:
        masofaviy boshqaruv dasturi yuborgan Alt+Tab ham Alt+Tab.
        """
        if not down:
            self.down_since.pop(vk, None)
            if vk in self.stuck:
                # Jismoniy UP keldi - OS'da u allaqachon qo'yib
                # yuborilgan, ikkinchi UP kerak emas.
                self.stuck.discard(vk)
                log.info("Yopishgan '%s' tugmasi qo'yib yuborildi", _VK_NAMES.get(vk, vk))
                return False
            if vk in self.swallowed:
                self.swallowed.discard(vk)
                return False
            return True
        if vk in self.stuck or vk in self.swallowed:
            # Yutilgan tugmaning auto-repeat'i - UP gacha yutiladi,
            # observer'ga qayta xabar qilinmaydi (urinish bitta).
            return False
        for combo in self.combos:
            if vk not in combo.vks:
                continue
            if all(any(self._key_is_down(code) for code in variants)
                   for variants in combo.required):
                self.swallowed.add(vk)
                if self._on_blocked is not None:
                    try:
                        self._on_blocked(combo.code)
                    except Exception:
                        # Observer xatosi bloklashni buzmasligi kerak.
                        log.debug("Qulflash observer xatosi", exc_info=True)
                return False
        if vk in _STUCK_AFTER_S:
            self.down_since.setdefault(vk, self._clock())
        return True

    def tick(self) -> None:
        """
        Yopishgan modifikator (nazoratchi thread'idan, soniyada bir).

        OS holati bilan TASDIQLANADI: hook ko'rmagan UP (Ctrl+Alt+Del,
        Win+L, UAC - xavfsiz ish stoli) bizning jadvalni eskirtiradi,
        lekin OS'da tugma allaqachon qo'yilgan - unda faqat yozuv
        o'chadi, hech narsa yuborilmaydi.
        """
        now = self._clock()
        for vk, since in list(self.down_since.items()):
            if now - since < _STUCK_AFTER_S[vk]:
                continue
            self.down_since.pop(vk, None)
            if not self._key_is_down(vk):
                continue
            self.stuck.add(vk)
            if self.release_key is not None:
                self.release_key(vk)
            name = _VK_NAMES.get(vk, str(vk))
            log.warning(
                "'%s' %.0f s dan beri bosilgan - yopishib qolgan deb mantiqan "
                "qo'yib yuborildi (klaviaturani tekshiring)", name, now - since,
            )
            self.report("stuck_key", name)


class _LocalEngine:
    """Zaxira: hook CLIENT jarayonining ichida (GIL raqobati bor)."""

    def __init__(self, policy: KeyPolicy, hook_factory) -> None:
        self._policy = policy
        self._hook = hook_factory(
            policy.on_key, on_tick=policy.tick,
            on_health=lambda state: policy.report("hook_" + state),
        )
        policy.release_key = self._hook.release_key

    @property
    def running(self) -> bool:
        return self._hook.running

    def start(self, codes: list) -> bool:
        self._policy.set_codes(codes)
        return self._hook.start()

    def update(self, codes: list) -> None:
        self._policy.set_codes(codes)

    def stop(self) -> None:
        self._hook.stop()
        self._policy.reset()


class _Lockdown:
    """
    Qulflash holati - yagona nusxa (`lockdown`).

    Holatni saqlash SHART: siyosat to'rt marta keladi (`.env`
    standarti ishga tushishda, keyin preflight, handshake va imtihon
    profili) va har biri oldingisini ALMASHTIRISHI kerak, ustiga
    qo'shmasligi. Aks holda bino sozlamasidan o'chirilgan tugma
    bloklangan holda qolardi. Qaysi ro'yxat qo'llanishini
    `resolve_hotkeys` hal qiladi.

    HOOK ALOHIDA JARAYONDA (`keyboard_hook_process`), client ichida EMAS.
    O'lchangan: client ichidagi Python hook'i parallel Python thread'lari
    GIL'ni band qilganda har tugmani median ~110 ms, eng ko'pi ~420 ms
    kechiktirdi - yozish sezilarli sekinlashadi va `LowLevelHooksTimeout`
    dan oshib, Windows hook'ni jimgina olib tashlaydi. Alohida jarayonda
    raqobat yo'q (bo'sh holatdagi ~0.1 ms). Jarayon ishga tushmasa -
    zaxira `_LocalEngine`, u ham canary bilan nazorat qilinadi.
    """

    def __init__(self, key_is_down=_key_is_down, *, hook_factory=KeyboardHook,
                 process_factory=None, clock=time.monotonic) -> None:
        self._hook_factory = hook_factory
        self._process_factory = process_factory
        self._key_is_down = key_is_down
        self._clock = clock
        self._engine = None
        self._active_keys: list[str] = []
        self._accessibility_saved: dict = {}
        self._lock = threading.RLock()
        self._cleanup_registered = False
        #: Bloklangan bosish haqida xabar qiluvchi (ixtiyoriy).
        self._observer: Optional[callable] = None
        #: Qulfning o'z nosozligi haqida xabar qiluvchi (ixtiyoriy).
        self._issue_observer: Optional[callable] = None

    def set_observer(self, observer: Optional[callable]) -> None:
        """
        Bloklangan tugma bosilganda chaqiriladigan funksiya.

        Nima uchun kerak: bloklashning O'ZI hodisa emas, lekin talabgor
        Alt+Tab ni QAYTA-QAYTA bosayotgani - eng aniq niyat belgisi.
        Usiz proktor faqat natijani (hech narsa bo'lmagan ekranni)
        ko'radi va urinishlarni umuman bilmaydi.

        DIQQAT: fon thread'idan chaqiriladi (qulf jarayonini o'quvchi yoki
        zaxira hook), UI thread'idan EMAS. Observer thread-safe bo'lishi
        shart (Qt signalini emit qilish - shunday).
        """
        self._observer = observer

    def set_issue_observer(self, observer: Optional[callable]) -> None:
        """
        Qulfning O'Z nosozligi: `observer(reason, key)`.

        `reason`: `stuck_key` (modifikator yopishib qolgan va qo'yib
        yuborildi, `key` - qaysi), `hook_restored` (hook olib tashlangan
        yoki qulf jarayoni o'lgan edi - tiklandi; oraliqda bloklash
        ishlamagan bo'lishi mumkin), `hook_lost` (tiklab bo'lmadi). Bular
        talabgorning aybi EMAS - proktor uchun "kuzatuv cheklangan"
        ma'lumoti. Fon thread'idan chaqiriladi.
        """
        self._issue_observer = observer

    def _notify(self, code: str) -> None:
        observer = self._observer
        if observer is None:
            return
        try:
            observer(code)
        except Exception:
            log.debug("Qulflash observer xatosi", exc_info=True)

    def _report(self, reason: str, key: str = "") -> None:
        observer = self._issue_observer
        if observer is None:
            return
        try:
            observer(reason, key)
        except Exception:
            log.debug("Qulflash nosozlik observer'i xatosi", exc_info=True)

    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        """Klaviatura hook'i shu platformada ishlaydimi (Windows)."""
        return _KEYBOARD_AVAILABLE

    @property
    def blocked_keys(self) -> list[str]:
        return list(self._active_keys)

    # ------------------------------------------------------------------
    def apply(self, keys: Optional[list] = None) -> list[str]:
        """
        Berilgan ro'yxatni qo'llaydi va bloklanadiganini qaytaradi.

        Idempotent: ro'yxat ALMASHTIRILADI. Hook esa QAYTA
        o'rnatilmaydi - faqat jadvali almashadi, ya'ni siyosat
        almashinuvida (preflight -> handshake -> imtihon) qulfsiz lahza
        yo'q. Xato bo'lgan bitta kod butun ro'yxatni yiqitmaydi - u
        o'tkazib yuboriladi va log'da qoladi, chunki panelga qo'lda
        kiritilgan "ctrl+shft+i" kabi xato yozuv tufayli qolgan
        tugmalar ochiq qolishi mumkin emas.
        """
        with self._lock:
            self._register_cleanup()
            self._disable_accessibility()

            _combos, blocked, failed = KeyPolicy.parse(keys)
            if failed:
                log.warning("Qulflash: bloklanmagan tugmalar: %s", failed)
            if not blocked:
                self._stop_engine()
                self._active_keys = []
                log.info("Qulflash: bloklanadigan tugmalar ro'yxati bo'sh")
                return []
            if not _KEYBOARD_AVAILABLE:
                log.warning("Qulflash ISHLAMAYDI (Windows emas). Tugmalar: %s", blocked)
                return []

            if self._engine is not None and self._engine.running:
                self._engine.update(blocked)
            elif not self._start_engine(blocked):
                self._active_keys = []
                log.error("Qulflash hook'i o'rnatilmadi - tugmalar bloklanmaydi")
                return []

            self._active_keys = blocked
            log.info("Qulflash: %s ta tugma bloklandi: %s", len(blocked), blocked)
            return blocked

    def release(self) -> None:
        """Hamma narsani asl holiga qaytaradi. Qayta chaqirish xavfsiz."""
        with self._lock:
            self._stop_engine()
            self._active_keys = []
            self._restore_accessibility()

    # ------------------------------------------------------------------
    def _start_engine(self, codes: list) -> bool:
        self._stop_engine()
        factory = self._process_factory
        if factory is None and self._hook_factory is KeyboardHook:
            from services.keyboard_hook_process import HookProcess

            factory = HookProcess
        if factory is not None:
            engine = factory(on_blocked=self._notify, on_issue=self._report)
            if engine.start(codes):
                self._engine = engine
                return True
            log.error("Klaviatura qulfi jarayoni ishga tushmadi - zaxira: client ichidagi hook")
        policy = KeyPolicy(
            key_is_down=self._key_is_down, clock=self._clock,
            on_blocked=self._notify, on_issue=self._report,
        )
        engine = _LocalEngine(policy, self._hook_factory)
        if engine.start(codes):
            self._engine = engine
            return True
        return False

    def _stop_engine(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.stop()
            except Exception as exc:
                log.debug("Qulf dvigateli to'xtatilmadi: %s", exc)

    def _register_cleanup(self) -> None:
        """
        Tiklashni dasturning HAR QANDAY tugashiga bog'laydi.

        `atexit` oddiy chiqishni va `sys.exit()` ni qamrab oladi;
        `excepthook` esa tutilmagan istisnoni. Ikkalasi ham bo'lmasa,
        yiqilgan dastur talaba mashinasida Sticky Keys'ni butunlay
        o'chirilgan holda qoldirardi.
        """
        if self._cleanup_registered:
            return
        atexit.register(self.release)

        previous_hook = sys.excepthook

        def _hook(exc_type, exc_value, traceback):
            try:
                self.release()
            finally:
                previous_hook(exc_type, exc_value, traceback)

        sys.excepthook = _hook
        self._cleanup_registered = True

    # ------------------------------------------------------------------
    # Windows Accessibility (Sticky / Filter / Toggle Keys)
    # ------------------------------------------------------------------
    #: (registry yo'li, qiymat nomi, "o'chirilgan" bayroqlari)
    _ACCESSIBILITY_KEYS = (
        (r"Control Panel\Accessibility\StickyKeys", "Flags", "506"),
        (r"Control Panel\Accessibility\FilterKeys", "Flags", "506"),
        (r"Control Panel\Accessibility\ToggleKeys", "Flags", "506"),
    )

    def _disable_accessibility(self) -> None:
        if sys.platform != "win32" or self._accessibility_saved:
            return
        try:
            import winreg
        except ImportError:
            return

        for path, name, disabled in self._ACCESSIBILITY_KEYS:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, path, 0,
                    winreg.KEY_READ | winreg.KEY_WRITE,
                ) as key:
                    try:
                        original, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        original = None
                    self._accessibility_saved[path] = original
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, disabled)
            except OSError as exc:
                log.debug("Accessibility o'chirilmadi (%s): %s", path, exc)

        self._apply_accessibility_now(enabled=False)
        log.info("Windows yordamchi yorliqlari o'chirildi (Sticky/Filter/Toggle)")

    def _restore_accessibility(self) -> None:
        if sys.platform != "win32" or not self._accessibility_saved:
            return
        try:
            import winreg
        except ImportError:
            return

        for path, name, _ in self._ACCESSIBILITY_KEYS:
            original = self._accessibility_saved.get(path)
            if original is None:
                continue
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE
                ) as key:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, original)
            except OSError as exc:
                log.debug("Accessibility tiklanmadi (%s): %s", path, exc)

        self._accessibility_saved.clear()
        self._apply_accessibility_now(enabled=True)
        log.info("Windows yordamchi yorliqlari tiklandi")

    @staticmethod
    def _apply_accessibility_now(*, enabled: bool) -> None:
        """
        O'zgarishni JORIY sessiyaga darhol qo'llaydi.

        Registry yozuvining o'zi yetarli emas: u qayta kirilgunga
        (logoff/logon) qadar kuchga kirmaydi. `SystemParametersInfo`
        esa o'sha zahoti ishlaydi.
        """
        try:
            import ctypes

            # SKF_STICKYKEYSON=1 | SKF_AVAILABLE=2 | SKF_HOTKEYACTIVE=4
            flags = 0x02 | 0x04 if enabled else 0x00

            class _Sticky(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint)]

            class _Filter(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint),
                    ("iWaitMSec", ctypes.c_uint), ("iDelayMSec", ctypes.c_uint),
                    ("iRepeatMSec", ctypes.c_uint), ("iBounceMSec", ctypes.c_uint),
                ]

            user32 = ctypes.windll.user32
            sticky = _Sticky(ctypes.sizeof(_Sticky), flags)
            user32.SystemParametersInfoW(0x003B, ctypes.sizeof(sticky), ctypes.byref(sticky), 0)

            filters = _Filter(ctypes.sizeof(_Filter), flags, 0, 0, 0, 0)
            user32.SystemParametersInfoW(0x003A, ctypes.sizeof(filters), ctypes.byref(filters), 0)

            toggle = _Sticky(ctypes.sizeof(_Sticky), flags)
            user32.SystemParametersInfoW(0x0035, ctypes.sizeof(toggle), ctypes.byref(toggle), 0)
        except Exception as exc:
            log.debug("SystemParametersInfo xatosi: %s", exc)


#: Yagona nusxa - OS holati global, demak uni boshqaruvchi ham bitta.
lockdown = _Lockdown()


# ----------------------------------------------------------------------
# Oyna qatlami: Windows System Menu
# ----------------------------------------------------------------------
#
# O'LCHANGAN (`tests/test_lockdown_hook.py` izohi): kiosk oynasi
# `self.windowFlags() | FramelessWindowHint` bilan qurilardi va QMainWindow
# standartidagi `WindowSystemMenuHint` saqlanib qolardi - `WS_SYSMENU`
# bor edi va oynaga yetgan Alt+Space ekran tepasida System Menu
# (Tiklash / Ko'chirish / O'lcham / Yopish) ochardi. Unga yetib borish
# uchun hook'ning bitta xatosi yoki Windows uni olib tashlagani kifoya.
# Shuning uchun menyu ikki marta yopiladi: oyna bayrog'ida (menyuning
# o'zi yo'q) va ilova filtrida (dialoglar, WebEngine va bayroqni Qt
# qaytarib qo'ygan holat ham qamraladi).

_WM_SYSKEYDOWN = 0x0104
_WM_SYSKEYUP = 0x0105
_WM_SYSCHAR = 0x0106
_WM_SYSCOMMAND = 0x0112
_VK_SPACE = 0x20
_SC_KEYMENU = 0xF100    # Alt / F10 / Alt+Space - klaviaturadan menyu
_SC_MOUSEMENU = 0xF090  # sarlavha belgisini bosish

_system_menu_guard = None


def kiosk_window_flags(flags):
    """
    Kiosk oynasining bayroqlari: System Menu'siz.

    `CustomizeWindowHint` SHART: usiz Qt bayroqlarni "moslashtiradi" va
    olib tashlangan `WindowSystemMenuHint` ni jimgina qaytarib qo'yadi.
    Min/Max/Close tugma bayroqlari ham OLIB TASHLANADI: ular qolsa Qt
    (`QWidgetPrivate::adjustFlags`) menyu bayrog'ini qaytaradi VA
    `FramelessWindowHint` ni O'CHIRADI - kiosk oynasiga ramka qaytardi
    (o'lchangan, `tests/test_lockdown_hook.py`). Oyna baribir
    ramkasiz - tugmalarni chizadigan joy yo'q.
    """
    from PyQt6.QtCore import Qt

    kind = Qt.WindowType
    strip = (
        kind.WindowSystemMenuHint
        | kind.WindowMinMaxButtonsHint
        | kind.WindowCloseButtonHint
        | kind.WindowContextHelpButtonHint
    )
    return (flags | kind.CustomizeWindowHint) & ~strip


def is_system_menu_message(message: int, wparam: int) -> bool:
    """Bu Windows xabari System Menu'ni ochishi mumkinmi (sof funksiya)."""
    if message in (_WM_SYSKEYDOWN, _WM_SYSKEYUP) and wparam == _VK_SPACE:
        # Qt'ning o'zi Alt+Space'da menyuni ochadi (WM_SYSKEYDOWN) -
        # DefWindowProc'ga yetmasdan.
        return True
    if message == _WM_SYSCHAR and wparam == _VK_SPACE:
        return True
    if message == _WM_SYSCOMMAND and (wparam & 0xFFF0) in (_SC_KEYMENU, _SC_MOUSEMENU):
        return True
    return False


def install_system_menu_guard(app) -> bool:
    """
    Ilovaning BARCHA oynalarida System Menu ochilishini to'sadi.

    Idempotent. Filtr obyektiga havola modulda saqlanadi - PyQt uni
    o'zi ushlamaydi va yig'ib olingan filtr jarayonni qulatardi.
    """
    global _system_menu_guard
    if _system_menu_guard is not None:
        return True
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    from PyQt6.QtCore import QAbstractNativeEventFilter

    class _SystemMenuFilter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            try:
                if bytes(event_type) == b"windows_generic_MSG":
                    msg = wintypes.MSG.from_address(int(message))
                    if is_system_menu_message(msg.message, msg.wParam):
                        return True, 0
            except Exception:
                pass
            return False, 0

    _system_menu_guard = _SystemMenuFilter()
    app.installNativeEventFilter(_system_menu_guard)
    log.info("Oyna qatlami: System Menu (Alt+Space, SC_KEYMENU) to'sildi")
    return True
