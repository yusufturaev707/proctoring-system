"""
Sahifa sarlavhasi - login'dan keyingi barcha sahifalarda bir xil.

Operator har doim ikki narsani ko'rib turishi kerak: qaysi bosqichda
turgani va qaysi binoda/kompyuterda ishlayotgani. Bu blok sahifalar
orasida ko'chirilmasligi uchun alohida vidjet.

IKKALA SARLAVHADA HAM chap yuqori burchakda LOGOTIP va TASHKILOT NOMI
(`_brand_block`; test nomi va xodim F.I.Sh. emas), o'ngda KOMPYUTER
RAQAMI (`brand.SeatBadge`) turadi. Ular sarlavha vidjetida,
sahifalarda emas: logotip uch sahifada bir xil joyda turishi kerak va
nusxa ko'chirilgan joylashuv vaqt o'tib albatta siljib ketardi. Imtihon
(test platformasi) sahifasida sarlavha yo'q — u yerda butun ekran
testniki.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.styles import COLORS, badge_style, surface_container_style
from ui.widgets.brand import BrandLogo, SeatBadge
from ui.widgets.icons import RefreshButton
from ui.widgets.md3 import FlowStepper
from version import COMPANY_NAME


class StepBadge(QLabel):
    """Bosqich raqami: 1/4, 2/4 ..."""

    def __init__(self, step: int, total: int, parent=None) -> None:
        super().__init__("{} / {}".format(step, total), parent)
        self.setStyleSheet(badge_style("info"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(24)


#: Sarlavhadagi logotip balandligi (px). Sarlavha matni (26 px) va
#: ostidagi qator bilan birga ~48 px — logotip ulardan baland bo'lsa
#: sarlavha qatori cho'zilib, butun sahifani pastga surardi.
HEADER_LOGO_HEIGHT = 44


def _brand_block(top: QHBoxLayout) -> tuple:
    """
    Chap burchak: logotip | tashkilot nomi, ostida bosqich (ikkala sarlavhada bir xil).

    SARLAVHA — TASHKILOT NOMI, test nomi yoki xodim F.I.Sh. EMAS. Ekran
    oldida talabgor turadi: unga "qaysi tashkilot imtihoni" ko'rinadi,
    xodim ismi esa unga ham, operatorga ham kerak emas (u kimligini
    biladi). Test nomi imtihon tanlash sahifasida tanlanadi.

    `(nom, bosqich)` yorliqlarini qaytaradi; bosqich bo'sh bo'lsa yashirin.
    """
    logo = BrandLogo(HEADER_LOGO_HEIGHT)
    top.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
    # Ajratgich faqat logotip bilan: fayl yo'q bo'lsa sarlavha chap
    # chetdan yolg'iz chiziq bilan boshlanardi.
    if not logo.pixmap().isNull():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedSize(1, 36)
        line.setStyleSheet("background-color: {}; border: none;".format(COLORS["border"]))
        top.addWidget(line, 0, Qt.AlignmentFlag.AlignVCenter)

    box = QVBoxLayout()
    box.setSpacing(2)
    # MD3 "title medium" (17 px), brend rangi: nom sahifa sarlavhasi
    # emas, logotipning davomi — 22 px qora matn sarlavhaning yarmini
    # egallab, o'ngdagi kompyuter raqami va kataklarni siqardi. Qatorni
    # 44 px logotipdan baland qilmaydi (`HEADER_LOGO_HEIGHT` izohi).
    name = QLabel(COMPANY_NAME)
    name.setStyleSheet(
        "font-size: 17px; font-weight: 700; letter-spacing: 0.2px; color: {};".format(
            COLORS["primary_deep"]
        )
    )
    box.addWidget(name)
    # Yorliq bo'sh bo'lsa ham yaratiladi: u keyin to'ldiriladi
    # (`set_subtitle`) va sarlavha balandligi o'zgarib, ostidagi butun
    # sahifa siljib ketmasligi kerak.
    subtitle = QLabel("")
    subtitle.setProperty("role", "subtitle")
    subtitle.hide()
    box.addWidget(subtitle)
    top.addLayout(box)
    return name, subtitle


class PageHeader(QWidget):
    """
    Sarlavha + kontekst + orqaga/chiqish tugmalari.

    KONTEKST IKKI SHAKLDA va tanlov sahifaga bog'liq:

        `chips=(...)`  - kataklarga bo'lingan panel (viloyat, bino,
                         IP). Qiymat NUSXALANADI va u nosozlikda
                         administratorga aytiladi.
        standart       - bitta kichik nishon (`set_context`).

    Ikkalasi birga TURMAYDI: bir xil ma'lumotni ikki ko'rinishda
    ko'rsatish sarlavhani og'irlashtiradi va operatorning ko'zi
    qaysi biriga qarashni bilmaydi.
    """

    logout_requested = pyqtSignal()
    back_requested = pyqtSignal()

    def __init__(
        self,
        subtitle: str = "",
        *,
        step: int = 0,
        total_steps: int = 4,
        show_back: bool = False,
        show_logout: bool = True,
        chips=None,
        stepper: bool = False,
        parent=None,
    ) -> None:
        """
        `stepper=True` - "2 / 4" nishoni o'rniga butun yo'l nomlari bilan
        (`md3.FlowStepper`), ajratuvchi chiziq ostida. Talabgor "qayerda
        turibman va keyin nima bo'ladi" ni o'qiydi, raqamdan emas.
        """
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)

        self.title_label, self.subtitle_label = _brand_block(top)
        self.set_subtitle(subtitle)

        if show_back:
            self.back_btn = QPushButton("< Orqaga")
            self.back_btn.setProperty("variant", "ghost")
            self.back_btn.setFixedWidth(130)
            self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.back_btn.clicked.connect(self.back_requested.emit)
            top.addWidget(self.back_btn)
        else:
            self.back_btn = None

        top.addStretch()

        if step and not stepper:
            top.addWidget(StepBadge(step, total_steps))

        if chips:
            self.chips = ContextChips(chips)
            self.context_label = None
            top.addWidget(self.chips)
        else:
            self.chips = None
            self.context_label = QLabel("")
            self.context_label.setStyleSheet(badge_style("muted"))
            self.context_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.context_label.setFixedHeight(24)
            top.addWidget(self.context_label)

        self.seat = SeatBadge()
        top.addWidget(self.seat, 0, Qt.AlignmentFlag.AlignVCenter)

        if show_logout:
            self.logout_btn = QPushButton("Chiqish")
            self.logout_btn.setProperty("variant", "ghost")
            self.logout_btn.setFixedWidth(120)
            self.logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.logout_btn.clicked.connect(self.logout_requested.emit)
            top.addWidget(self.logout_btn)
        else:
            self.logout_btn = None

        root.addLayout(top)

        divider = QFrame()
        divider.setProperty("role", "divider")
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: {};".format(COLORS["border"]))
        root.addWidget(divider)

        self.stepper = FlowStepper(step) if stepper and step else None
        if self.stepper is not None:
            root.addWidget(self.stepper, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def set_context(self, text: str) -> None:
        """O'ng yuqoridagi kontekst: "1-bino - operator Ali"."""
        if self.context_label is None:
            return
        self.context_label.setText(text)
        self.context_label.setVisible(bool(text))

    def set_chips(self, **values) -> None:
        """Kataklarga bo'lingan kontekst (`chips=` bilan yaratilganda)."""
        if self.chips is not None:
            self.chips.set_values(**values)

    def set_seat(self, device) -> None:
        """Kompyuter raqami (`AppState.device`) — o'ng tomondagi nishon."""
        self.seat.set_seat(device.number, device.computer_label, code=device.inventory_code)


def ip_chip_hints(addresses) -> tuple:
    """
    Bir nechta IP bo'lgan holat uchun `(tooltips, captions)`.

    Mashinada bittadan ortiq manzil bo'lishi ODATIY hol: Hyper-V
    va WSL o'z adapterini qo'shadi, provayder ikkinchi manzil
    beradi, administrator qo'lda statik manzil qo'shadi. Katakda
    ularning HAMMASINI ko'rsatib bo'lmaydi, bittasini jimgina
    tanlash esa xato edi - panelda ikkinchi darajali manzil
    ko'rinib, operator uni administratorga aytganda hech qayerda
    topilmasdi.

    Yechim uch qismli: katakda ASOSIY manzil (marshrut tanlagani),
    yorliqda nechtaligi, tooltip'da to'liq ro'yxat adapter nomlari
    bilan. Bitta manzil bo'lsa hech narsa qo'shilmaydi - ortiqcha
    "· 1 ta" faqat shovqin.
    """
    entries = list(addresses or [])
    if len(entries) < 2:
        return {}, {}
    lines = "\n".join(
        "{}{}".format(ip, "  —  {}".format(name) if name else "") for name, ip in entries
    )
    return (
        {"ip": "Mashinaning barcha IPv4 manzillari:\n{}".format(lines)},
        {"ip": "IP · {} ta".format(len(entries))},
    )


class _ElidedValue(QLabel):
    """
    Uzun qiymat ("…Qoraqalpog'iston Respublikasidagi binosi") "…" bilan
    qisqaradi, to'liq matn tooltip'da.

    Oddiy `QLabel` minimal kengligini to'liq matndan oladi: panelda
    kiritilgan uzun bino nomi butun sahifani 1366 px dan kengaytirib
    yuborardi (jonli smoke: 1458 / 1703 px) va o'ng chet - kompyuter
    raqami, «Davom etish» - ekrandan chiqib qolardi.
    """

    _MIN_WIDTH = 90

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._full = text
        self._tip = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full = text or ""
        self._elide()

    def setToolTip(self, text: str) -> None:  # noqa: N802 - Qt API
        self._tip = text or ""
        self._elide()

    def full_text(self) -> str:
        return self._full

    def sizeHint(self):  # noqa: N802 - Qt API
        hint = super().sizeHint()
        hint.setWidth(self.fontMetrics().horizontalAdvance(self._full) + 4)
        return hint

    def minimumSizeHint(self):  # noqa: N802 - Qt API
        hint = super().minimumSizeHint()
        hint.setWidth(min(self._MIN_WIDTH, self.sizeHint().width()))
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(self._MIN_WIDTH, self.width())
        )
        QLabel.setText(self, shown)
        # Qisqargan bo'lsa to'liq nom tooltip'da (chaqiruvchi o'z
        # tooltip'ini bergan bo'lsa - o'shanisi).
        QLabel.setToolTip(self, self._tip or (self._full if shown != self._full else ""))


class ContextChips(QFrame):
    """
    Ish o'rni konteksti: viloyat, bino, kompyuter, MAC, IP.

    NIMA UCHUN AYNAN SHULAR. Ular birgalikda bitta savolga javob
    beradi: "men to'g'ri mashinadamanmi?". Operator kuniga o'nlab
    mashinada ishlaydi va nosozlikda administratorga aynan shu
    qiymatlarni aytadi - MAC bilan mashina bazada topiladi, IP
    bilan tarmoqdagi o'rni, bino bilan esa handshake to'g'ri
    binoni aniqlaganini tekshiriladi. Kompyuter raqami esa o'sha
    savolga ODAM TILIDA javob beradi: u stolga yozilgan va
    operator mashinani aynan shu bilan ataydi.

    QAYSI KATAK KO'RSATILISHI SAHIFAGA BOG'LIQ (`fields`). Imtihon
    tanlash ekranida hammasi kerak - u yerda mashina
    tekshiriladi. Talabgor bilan ishlash ekranlarida esa MAC ortiqcha:
    o'sha paytda savol mashina haqida emas, talabgor haqida va
    ekrandagi har bir ortiqcha raqam asosiy ma'lumotni siqib
    chiqaradi.

    QIYMAT NUSXALANADIGAN bo'lishi kerak, shuning uchun ular oddiy
    matn (`QLabel`), tugma yoki nishon emas: operator sichqoncha
    bilan belgilab, telefonda aytish o'rniga xabarga qo'yib
    yuborishi mumkin.
    """

    #: Qisqarishi mumkin bo'lgan kataklar (nomlar - panelda erkin matn).
    #: MAC va IP hech qachon qisqarmaydi: ular aynan nusxalanadi.
    ELIDED = frozenset({"region", "zone"})

    #: Mumkin bo'lgan kataklar. Tartib ma'noli: kattadan kichikka -
    #: viloyat, bino, xonadagi o'rin, keyin mashinaning o'zi.
    #:
    #: KOMPYUTER RAQAMI aynan shu yerda: u "qaysi mashinadaman?"
    #: degan savolga odam tilida javob beradi. MAC va IP o'sha
    #: savolga texnik tilda javob beradi va ular administrator
    #: uchun; operator esa stolda yozilgan raqamni ko'radi.
    FIELDS = (
        ("region", "Viloyat"),
        ("zone", "Bino"),
        ("pc", "Kompyuter"),
        ("mac", "MAC"),
        ("ip", "IP"),
    )

    def __init__(self, fields=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("contextChips")
        self._tone = "low"
        self.setStyleSheet(surface_container_style("contextChips"))

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 9, 18, 9)
        root.setSpacing(0)

        wanted = tuple(fields) if fields else tuple(key for key, _ in self.FIELDS)
        self._labels: dict = {}
        #: key -> (yorliq vidjeti, standart matn). Yorliq qo'shimcha
        #: ma'lumot ko'rsatishi mumkin ("IP · 3 ta"), shuning uchun
        #: standart matn ham saqlanadi - uni qaytarish uchun.
        self._captions: dict = {}
        for index, (key, caption) in enumerate(
            item for item in self.FIELDS if item[0] in wanted
        ):
            if index:
                root.addWidget(self._separator())

            cell = QVBoxLayout()
            cell.setSpacing(1)
            cell.setContentsMargins(12 if index else 0, 0, 12, 0)

            title = QLabel(caption)
            title.setStyleSheet(
                "font-size: 11px; font-weight: 700; letter-spacing: 0.6px; color: {};".format(
                    COLORS["text_muted"]
                )
            )
            cell.addWidget(title)
            self._captions[key] = (title, caption)

            value = _ElidedValue("—") if key in self.ELIDED else QLabel("—")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet(
                "font-size: 14px; font-weight: 600; color: {};".format(COLORS["text"])
            )
            cell.addWidget(value)

            self._labels[key] = value
            # Bo'sh joy nomlarga beriladi (bino eng uzuni) - qisqarish
            # faqat haqiqatan sig'masa.
            root.addLayout(cell, 1 if key in self.ELIDED else 0)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        line.setStyleSheet("background-color: {}; border: none;".format(COLORS["border"]))
        return line

    def set_values(self, *, region: str = "", zone: str = "", pc: str = "",
                   mac: str = "", ip: str = "",
                   ok: bool = True, tooltips: dict = None, captions: dict = None) -> None:
        """
        `ok=False` - kompyuter bazada topilmagan.

        Rang bilan CHEKLANMAYDI: bino qiymati ham "aniqlanmadi" ga
        o'zgaradi. Faqat qizil fon rang ajratolmaydigan operator
        uchun hech narsa demaydi.

        Ko'rsatilmaydigan katakning qiymati JIMGINA tashlanadi -
        chaqiruvchi qaysi kataklar yoqilganini bilishi shart emas.

        `tooltips` va `captions` - ixtiyoriy `{key: matn}` lug'atlari.
        Ular mashinada bir nechta IP bo'lgan holat uchun: katakda
        ASOSIY manzil turadi (marshrut tanlagani), yorliq nechtaligini
        aytadi ("IP · 3 ta"), to'liq ro'yxat esa tooltip'da. Uchalasini
        katakka sig'dirish qatorni o'qib bo'lmas holga keltirardi.
        """
        tooltips = tooltips or {}
        captions = captions or {}
        for key, value in (
            ("region", region), ("zone", zone), ("pc", pc), ("mac", mac), ("ip", ip)
        ):
            label = self._labels.get(key)
            if label is None:
                continue
            label.setText(value or "—")
            label.setToolTip(tooltips.get(key, ""))

            title, default = self._captions.get(key, (None, ""))
            if title is not None:
                title.setText(captions.get(key) or default)
                title.setToolTip(tooltips.get(key, ""))

        tone = "low" if ok else "error"
        if tone != self._tone:
            self._tone = tone
            self.setStyleSheet(surface_container_style("contextChips", tone=tone))


class WorkstationHeader(QWidget):
    """
    Ish o'rni sarlavhasi: tashkilot | kontekst | yangilash.

    `PageHeader` dan ALOHIDA va uni almashtirmaydi. Ikkalasi boshqa
    savolga javob beradi:

        PageHeader          - "men oqimning qaysi bosqichidaman?"
                              (sarlavha, qadam raqami, orqaga/chiqish)
        WorkstationHeader   - "men qaysi mashinada va kim sifatida
                              ishlayapman?"

    Ikkinchisi imtihon tanlash ekranida kerak: operator kun boshida
    aynan shu ekranda mashinani tekshiradi. Keyingi bosqichlarda
    (talabgor, FaceID) esa savol yana oqimga qaytadi va u yerda
    `PageHeader` qoladi.

    CHIQISH TUGMASI BU YERDA YO'Q. U ataylab olib tashlangan: o'ng
    burchakda faqat bitta amal turishi kerak, aks holda operator
    "Yangilash" o'rniga "Chiqish" ni bosib qo'yadi - ikkalasi yonma-yon
    turganda bu muqarrar. Hisobdan chiqish yo'li saqlanadi va u
    Ctrl+Q dialogidagi "Hisobdan chiqib, login sahifasiga qaytish"
    tugmasi (`MainWindow._back_action`).
    """

    reload_requested = pyqtSignal()

    def __init__(self, parent=None, *, step: int = 0) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(20)

        # --- Chap: tashkilot nomi va bosqich (xodim F.I.Sh. YO'Q —
        # `_brand_block` izohi) ---
        self.title_label, self.subtitle_label = _brand_block(top)

        top.addStretch(1)

        # --- O'rta: kontekst ---
        # KOMPYUTER katagi bu yerda YO'Q: raqam o'ngdagi yirik nishonda
        # (`SeatBadge`). Ikkala joyda turishi bir qiymatni ikki xil
        # o'lchamda ko'rsatardi.
        self.context = ContextChips(fields=("region", "zone", "mac", "ip"))
        top.addWidget(self.context)

        top.addStretch(1)

        # --- O'ng: kompyuter raqami va yangilash ---
        self.seat = SeatBadge()
        top.addWidget(self.seat, 0, Qt.AlignmentFlag.AlignVCenter)

        self.reload_btn = RefreshButton(42)
        self.reload_btn.clicked.connect(self.reload_requested.emit)
        top.addWidget(self.reload_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addLayout(top)

        divider = QFrame()
        divider.setProperty("role", "divider")
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: {};".format(COLORS["border"]))
        root.addWidget(divider)

        # Oqim bosqichlari (`PageHeader(stepper=True)` bilan bir xil).
        self.stepper = FlowStepper(step) if step else None
        if self.stepper is not None:
            root.addWidget(self.stepper, 0, Qt.AlignmentFlag.AlignHCenter)

    # ------------------------------------------------------------------
    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def set_context(self, **values) -> None:
        self.context.set_values(**values)

    def set_seat(self, device) -> None:
        self.seat.set_seat(device.number, device.computer_label, code=device.inventory_code)

    def set_reloading(self, busy: bool) -> None:
        self.reload_btn.set_busy(busy)
