"""
Kamera paneli - rollar, jonli oldindan ko'rish va boshqaruv.

QAYTA ISHLATILADIGAN BLOK: imtihon tanlash sahifasining o'ng ustuni
va (keyinchalik) alohida kamera tekshiruvi sahifasi bir xil savolga
javob beradi - "bu ish o'rnida kuzatuv ishlaydimi?". Ikki joyda ikki
xil ko'rinish bo'lsa, operator ularni solishtirib chalkashadi.

UCH QATLAM VA ULARNING CHEGARASI:

    roles.resolve()  - QAROR: qaysi kamera nima uchun. Sof funksiya,
                       UI ni bilmaydi.
    CameraManager    - RESURS: oqim, thread, qayta ulanish.
    bu vidjet        - KO'RSATISH: qaror va resursni ekranga chiqaradi.

Vidjet hech qanday rol qarorini O'ZI qabul qilmaydi - u faqat
`roles.resolve()` natijasini chizadi. Shuning uchun qoidani
o'zgartirish uchun bu faylga tegish shart emas.

HAR BIR KAMERA - ALOHIDA KADR. Ilgari bitta oldindan ko'rish maydoni
bor edi va kameralar orasida chip bilan almashtirilardi. Bu noto'g'ri
edi: ikkala kamera imtihon davomida BIR VAQTDA ishlaydi va operator
ularni aynan birga ko'rishi kerak - yuz kamerasi talabgorga,
ikkinchisi stolga qaratilganini tekshirish uchun kadrlarni navbat
bilan ochib solishtirish kerak bo'lardi. Almashtirish yana bir
narsani yashirardi: ikkinchi kamera oqimi umuman ochilmagan bo'lishi
mumkin va buni faqat chipni bosganda bilinardi.

OLDINDAN KO'RISH ATAYLAB QO'LDA ISHGA TUSHIRILADI. Sahifa ochilishi
bilan kamerani ochish uch narsani buzardi:

  * Windows'da qurilma ochilishi ~0.8 s va u UI ni tutib qoladi;
  * keyingi sahifa (FaceID) o'sha kamerani ochishi kerak, band
    qurilma esa ochilmaydi;
  * talabgor hali kelmagan bo'lishi mumkin va uning tasviri
    bekorga ekranda turardi.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from proctoring.camera import CameraManager
from proctoring.camera import measure as camera_measure
from proctoring.camera import roles as camera_roles
from services.workers import ApiWorker, WorkerHolder
from ui.styles import (
    badge_style,
    preview_surface_style,
    segmented_button_style,
    surface_container_style,
    text_button_style,
    tonal_button_style,
)

log = logging.getLogger(__name__)

#: Oldindan ko'rish balandligi — bitta qiymat, kamera soniga
#: BOG'LIQ EMAS.
#:
#: Ilgari ikkita qiymat bor edi: ikkita kadr USTMA-UST turgani
#: uchun juftlik pastroq bo'lardi (146 px). Endi kartalar YONMA-YON
#: (`_SLOTS_PER_ROW`), ya'ni ikkinchi kadr birinchisining tepasidan
#: balandlik o'g'irlamaydi — ikkalasi ham to'liq o'lchamda ko'rinadi
#: va kamera burchagini shu yerdan baholash mumkin bo'ladi.
#:
#: Balandlik QAT'IY: kadr kelishi bilan maydon "sakrab" o'lchamini
#: o'zgartirsa, ostidagi tugmalar siljiydi va operator bosayotgan
#: tugmasini yo'qotadi.
_PREVIEW_HEIGHT = 208

#: Bitta qatordagi kamera kartalari soni (Bootstrap `col-md-6`
#: kabi — har biri kenglikning yarmi).
#:
#: Ikkita kamera VERTIKAL joylashganda karta juftligi ~600 px
#: egallardi va uning ostidagi tekshiruv natijalari ekrandan
#: chiqib ketardi. Yonma-yon joylashuv o'sha balandlikni ikki
#: barobar qisqartiradi — bu tekshiruv ro'yxati uchun bo'shatilgan
#: joyning asosiy qismi.
_SLOTS_PER_ROW = 2

#: Tekshiruv natijalari ro'yxatining chegaralari (px).
#:
#: Server 14 tagacha tekshiruv qaytaradi (`camera_check.evaluate`)
#: va ular kartaga sig'maydi: pastdagi qatorlar ekrandan chiqib
#: ketardi, "Tekshirish" tugmasi esa ular bilan birga. Chegara
#: qo'yilgach ro'yxat SCROLL bo'ladi — tugmalar har doim
#: ko'rinadigan joyda qoladi.
#:
#: MINIMUM ham kerak va u pastroq: 1366x768 ekranda kartaga
#: shuncha ham joy qolmasligi mumkin, o'shanda ro'yxat butunlay
#: siqilib, o'rniga bo'sh oraliq qolardi.
_CHECKS_MAX_HEIGHT = 360
_CHECKS_MIN_HEIGHT = 96

#: Tekshiruvdan oldin kameralar shuncha ishlab turadi (ms).
#:
#: FPS o'lchovi vaqt oynasiga tayanadi (`CameraStream._measured_fps`
#: oxirgi 30 kadr bo'yicha hisoblaydi) va oqim endigina ochilganda u
#: haqiqatdan ANCHA past chiqadi - kamera ekspozitsiyani sozlayotgan
#: bo'ladi. Kutmasdan o'lchash har bir tekshiruvda soxta "FPS past"
#: xatosini berardi.
_WARMUP_MS = 4000


class CameraPreview(QLabel):
    """
    Jonli kadr yoki tushuntiruvchi bo'shliq.

    `CameraView` dan ALOHIDA: u FaceID uchun va yuz ramkasi, ball,
    holat matnini chizadi. Bu yerda esa hech qanday tahlil yo'q -
    faqat "kamera ishlayaptimi" degan savolga javob. Ikkalasini
    birlashtirish bu vidjetga kerak bo'lmagan yuz mantig'ini olib
    kirardi.
    """

    def __init__(self, height: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(preview_surface_style())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def show_placeholder(self, text: str) -> None:
        self.setPixmap(QPixmap())
        self.setText(text)

    def show_frame(self, frame) -> None:
        height, width = frame.shape[:2]
        # BGR (OpenCV) -> RGB (Qt). `.copy()` MAJBURIY: `QImage`
        # buferga referens ushlaydi, nusxa olmaydi - massiv Python
        # tomonda yo'q qilinsa rasm buziladi yoki dastur qulaydi
        # (`widgets/camera_view.py` dagi bilan bir xil tuzoq).
        rgb = frame[:, :, ::-1].copy()
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888)
        self.setText("")
        self.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


def _by_device(cameras: list) -> list:
    """
    Kameralarni QURILMA bo'yicha barqaror tartibga soladi.

    Tartib: avval lokal veb-kameralar (indeks bo'yicha), keyin IP
    kameralar (manzil bo'yicha). Rol bu yerda umuman qatnashmaydi -
    aynan shuning uchun rol o'zgarganda kartalar joyidan
    ko'chmaydi.
    """
    return sorted(
        cameras,
        key=lambda camera: (
            camera.source != "local",
            camera.local_index if camera.local_index is not None else 99,
            camera.address,
            camera.label,
        ),
    )


class RoleSegmentedControl(QWidget):
    """
    Kamera qaysi vazifani bajaradi — MD3 segmented button.

    NIMA UCHUN OPERATOR TANLAYDI. Zaxira qoida kameralarni TARTIB
    bo'yicha taqsimlaydi (`camera/roles.py`), lekin OS'dagi indeks
    jismoniy joylashuvni bilmaydi: monitorga o'rnatilgan kamera
    1-indeksda, stolga qaragan USB kamera esa 0-indeksda bo'lishi
    mumkin. O'shanda taxmin teskari chiqadi va tahlil JIMGINA
    buziladi — yuz modeli stol ustidan yuz qidiradi.

    Buni faqat odam tuzata oladi: u ikkala kadrni ekranda ko'rib
    turibdi. Shuning uchun tanlov aynan KADR YONIDA turadi — alohida
    sozlama oynasida emas, u yerda solishtiradigan hech narsa
    bo'lmasdi.
    """

    #: `(kamera kaliti, vazifa)` — vazifa `face`, `objects` yoki `spare`.
    chosen = pyqtSignal(str, str)

    #: UCHINCHI SEGMENT - "Ishlatilmaydi". Binodagi IP kamera ikkita
    #: veb-kamerali mashinada uchinchi qurilma bo'ladi va unga vazifa
    #: berish uchun boshqa kameradan vazifani OLISH ham kerak. Tanlov
    #: almashtirish qoidasi bilan ishlaydi (`roles.assign`): vazifani
    #: olgan kamera o'zining eski vazifasini oldingi egasiga beradi.
    _SEGMENTS = (
        ("face", "Yuz tekshiruvi"),
        ("objects", "Obyekt aniqlash"),
        ("spare", "Ishlatilmaydi"),
    )

    def __init__(self, camera, *, can_spare: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._key = camera.key

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        # Oraliq NOL: segmentlar bir-biriga tegib turishi kerak,
        # aks holda ular oddiy tugmalarga aylanadi va "bittasini
        # tanlash" ma'nosi yo'qoladi.
        row.setSpacing(0)

        current = camera.purpose
        last = len(self._SEGMENTS) - 1
        for index, (purpose, label) in enumerate(self._SEGMENTS):
            selected = purpose == current
            position = "left" if index == 0 else "right" if index == last else "middle"
            button = QPushButton(("✓ " if selected else "") + label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(segmented_button_style(selected=selected, position=position))
            # Tanlangan segment BOSILMAYDI: u allaqachon joriy holat.
            # "Ishlatilmaydi" yolg'iz yuz kamerasida ham yopiq: uni
            # o'chirish shaxs tekshiruvini butunlay o'chirib qo'yardi.
            enabled = not selected and (purpose != "spare" or can_spare)
            button.setEnabled(enabled)
            if purpose == "spare" and not can_spare and not selected:
                button.setToolTip("Yuz tekshiruvi uchun boshqa kamera yo'q")
            button.clicked.connect(
                lambda _checked=False, value=purpose: self.chosen.emit(self._key, value)
            )
            # Teng cho'zilma: matn o'zgarganda (✓ qo'shilganda)
            # segmentlar joyidan siljimaydi.
            row.addWidget(button, 1)


class CameraSlotView(QFrame):
    """
    Bitta kamera: kadr + vazifa + tafsilot + o'z tekshiruvi.

    Kadr va tavsif BIRGA turadi va bu ataylab: ikkita kadr va
    ulardan alohida ikkita tavsif qatori bo'lsa, operator qaysi
    tavsif qaysi kadrga tegishli ekanini tartib bo'yicha taxmin
    qilishga majbur bo'lardi.

    TEKSHIRISH TUGMASI HAM SHU YERDA. Kameralar alohida tekshiriladi:
    odatda yuz kamerasi yetadi (aynan u shaxsni aniqlaydi), ikkinchisi
    esa siyosat talab qilsagina. Umumiy bitta tugma ikkalasini har
    safar birga tekshirishga majbur qilardi — bu esa ikkinchi
    kamerani ochish uchun qo'shimcha kutish va ko'pincha keraksiz.
    """

    #: `(kamera kaliti, vazifa)`.
    role_chosen = pyqtSignal(str, str)
    #: Shu kamerani tekshirish so'raldi (rol nomi).
    check_requested = pyqtSignal(str)

    _STATE_BADGE = {"ready": "success", "warning": "warning", "failed": "error"}
    _STATE_TEXT = {
        "ready": "Tekshiruvdan o'tdi",
        "warning": "Ogohlantirish bilan",
        "failed": "Tekshiruvdan o'tmadi",
    }

    def __init__(
        self,
        camera: camera_roles.ResolvedCamera,
        *,
        height: int,
        can_choose: bool = False,
        can_spare: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.role = camera.role
        #: Oldindan ko'rish sloti - rolli kamerada rolning o'zi, zaxirada
        #: `spare:<kalit>` (`ResolvedCamera.slot_id`).
        self.slot_id = camera.slot_id
        # Qurilma kimligi kartada QOLADI: rol o'zgaradi, qurilma esa
        # yo'q - tartib va tekshiruvlar shunga bog'lanadi.
        self.camera_key = camera.key
        self.camera_label = camera.label
        self.setObjectName("cameraSlot")
        self.setStyleSheet(
            surface_container_style(
                "cameraSlot", tone="low" if camera.available else "error"
            )
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.preview = CameraPreview(height)
        self.preview.show_placeholder(
            "Kadr uchun pastdagi tugmani bosing" if camera.available else "Kamera ishlamaydi"
        )
        root.addWidget(self.preview)

        top = QHBoxLayout()
        top.setSpacing(10)

        if can_choose:
            # Nishon o'rnida TANLOV: rol taxmin qilingan va uni
            # tuzatish mumkin. Ikkalasini birga ko'rsatish bir xil
            # ma'lumotni ikki marta yozardi.
            control = RoleSegmentedControl(camera, can_spare=can_spare)
            control.chosen.connect(self.role_chosen)
            top.addWidget(control, 1)
        else:
            purpose = QLabel(camera.purpose_label)
            purpose.setStyleSheet(
                badge_style("success" if camera.available and camera.in_use else "muted")
            )
            purpose.setFixedHeight(24)
            top.addWidget(purpose)
            top.addStretch(1)

        status = QLabel("Tayyor" if camera.available else "Ishlamaydi")
        status.setStyleSheet(badge_style("success" if camera.available else "error"))
        status.setFixedHeight(24)
        top.addWidget(status)
        root.addLayout(top)

        name = QLabel(camera.label or "Nomsiz kamera")
        name.setStyleSheet("font-size: 14px; font-weight: 600;")
        name.setWordWrap(True)
        root.addWidget(name)

        # Tafsilot HAR DOIM ko'rsatiladi: aynan u "nega ishlamayapti"
        # degan savolga javob beradi va operator uni administratorga
        # aytadi.
        details = [camera.reason]
        if camera.source == "ip" and camera.address:
            details.append(camera.address)
        elif camera.local_index is not None:
            details.append("qurilma #{}".format(camera.local_index))
        if camera.resolution:
            details.append(camera.resolution)
        if camera.is_virtual:
            details.append("virtual kamera")

        caption = QLabel("  •  ".join(part for part in details if part))
        caption.setProperty("role", "caption")
        caption.setWordWrap(True)
        root.addWidget(caption)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.check_btn = QPushButton("Tekshirish")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.setStyleSheet(text_button_style(32))
        self.check_btn.setToolTip("Faqat shu kamerani o'lchab, serverga baholatadi")
        # ZAXIRADAGI kamera tekshirilmaydi: server faqat vazifasi bor
        # kameralarni baholaydi va imtihonda faqat ular ishlaydi.
        if not camera.in_use:
            self.check_btn.setEnabled(False)
            self.check_btn.setToolTip("Avval kameraga vazifa bering")
        self.check_btn.clicked.connect(
            lambda: self.check_requested.emit(self.role)
        )
        bottom.addWidget(self.check_btn)
        bottom.addStretch(1)

        self.check_badge = QLabel("Tekshirilmagan")
        self.check_badge.setStyleSheet(badge_style("muted"))
        self.check_badge.setFixedHeight(24)
        bottom.addWidget(self.check_badge)
        root.addLayout(bottom)

    def set_check_state(self, summary: dict) -> None:
        """
        Server bergan xulosani nishonga chiqaradi.

        Bo'sh lug'at — tekshiruv umuman o'tkazilmagan. "Tekshirilmagan"
        va "tekshirildi, muammo yo'q" ni bir xil ko'rsatish operatorga
        tekshiruv o'tganini bilishga imkon bermasdi.
        """
        if not summary or not summary.get("checked"):
            self.check_badge.setText("Tekshirilmagan")
            self.check_badge.setStyleSheet(badge_style("muted"))
            return
        status = summary.get("status", "ready")
        self.check_badge.setText(self._STATE_TEXT.get(status, "Tekshirildi"))
        self.check_badge.setStyleSheet(
            badge_style(self._STATE_BADGE.get(status, "muted"))
        )

    def set_busy(self, busy: bool, *, mine: bool = True) -> None:
        """Tekshiruv ketayotganda tugma bloklanadi (barcha kartalarda)."""
        self.check_btn.setEnabled(not busy and bool(self.role))
        if busy and mine:
            self.check_btn.setText("Tekshirilmoqda...")
        elif not busy:
            self.check_btn.setText("Tekshirish")


class CheckRow(QFrame):
    """
    Bitta tekshiruv natijasi: nishon + sarlavha + tafsilot.

    Matn SERVERDAN keladi va client uni tarjima qilmaydi. Sabab
    `services/camera_check.py` dagi bilan bir xil: chegara ham,
    sabab ham bitta joyda yashashi kerak. Client tomonda matn
    yasash ikkalasining ajralib ketishiga olib kelardi - server
    "FPS past" deb hisoblab, ekranda "hammasi joyida" turardi.
    """

    _TONE = {"ready": "low", "warning": "low", "failed": "error"}
    _BADGE = {"ready": "success", "warning": "warning", "failed": "error"}
    _MARK = {"ready": "OK", "warning": "!", "failed": "X"}

    def __init__(self, check: dict, index: int, parent=None) -> None:
        super().__init__(parent)
        status = check.get("status", "ready")
        name = "checkRow{}".format(index)
        self.setObjectName(name)
        self.setStyleSheet(
            surface_container_style(name, tone=self._TONE.get(status, "low"))
        )

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        mark = QLabel(self._MARK.get(status, "?"))
        mark.setStyleSheet(badge_style(self._BADGE.get(status, "muted")))
        mark.setFixedHeight(22)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setMinimumWidth(38)
        root.addWidget(mark)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)

        title = QLabel(check.get("title", ""))
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        title.setWordWrap(True)
        text_box.addWidget(title)

        detail = check.get("detail") or ""
        if detail:
            caption = QLabel(detail)
            caption.setProperty("role", "caption")
            caption.setWordWrap(True)
            text_box.addWidget(caption)
        root.addLayout(text_box, 1)


class CameraPanel(QFrame):
    """Kuzatuv kameralari kartasi."""

    #: Rollar aniqlangach - sahifa uni `AppState` ga yozadi.
    layout_resolved = pyqtSignal(object)
    #: Server baholagan tekshiruv natijasi (`camera/check/` javobi).
    check_completed = pyqtSignal(object)

    def __init__(self, repo, *, show_reload: bool = True, parent=None) -> None:
        """
        `show_reload=False` - sahifada UMUMIY yangilash tugmasi bor.

        Bitta ekranda ikkita "Yangilash" tugmasi bo'lishi mumkin
        emas: operator qaysi biri nimani yangilashini eslab qolmaydi
        va nosozlikda ikkalasini navbat bilan bosadi.
        """
        super().__init__(parent)
        self.setProperty("role", "card")

        self._repo = repo
        self._workers = WorkerHolder()
        self._manager = CameraManager(self)
        self._manager.frame_ready.connect(self._on_frame)
        self._manager.state_changed.connect(self._on_camera_state)
        self._manager.devices_discovered.connect(self._on_devices)

        self._layout_result = camera_roles.CameraLayout()
        self._handshake_cameras: list = []
        self._views: dict = {}
        self._previewing = False
        self._busy = False
        self._checking = False
        self._check_result: dict = {}
        self._exam_id = None
        #: Operator tanlagan YUZ kamerasi (`ResolvedCamera.key`).
        #
        # Kalit saqlanadi, ROL emas: yangilashdan keyin qurilmalar
        # qaytadan aniqlanadi va rollar noldan taqsimlanadi - tanlov
        # esa qurilmaning o'ziga tegishli va u yo'qolmasligi kerak.
        #: Operator tanlovi `{qurilma kaliti: vazifa}` - "Yangilash"
        #: dan keyin ham saqlanadi (`roles.apply_choices`).
        self._choices: dict = {}
        #: Shu tekshiruvda qaysi rollar o'lchanadi (`None` - hammasi).
        self._check_roles = None
        #: Manager qaysi slotlar bilan sozlangan (`rol -> qurilma`).
        #: Bo'sh - hali sozlanmagan.
        self._configured: tuple = ()

        # Isitish taymeri: kameralar ochilgach shu vaqt o'tgandan
        # keyin o'lchov olinadi.
        self._warmup = QTimer(self)
        self._warmup.setSingleShot(True)
        self._warmup.timeout.connect(self._collect_measurements)

        self._setup_ui(show_reload)

    # ------------------------------------------------------------------
    def _setup_ui(self, show_reload: bool) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Kuzatuv kameralari")
        title.setProperty("role", "value")
        header.addWidget(title, 1)

        if show_reload:
            self.reload_btn = QPushButton("Yangilash")
            self.reload_btn.setToolTip("Kameralarni qayta aniqlash")
            self.reload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.reload_btn.setStyleSheet(text_button_style(34))
            self.reload_btn.clicked.connect(self.reload)
            header.addWidget(self.reload_btn)
        else:
            self.reload_btn = None
        root.addLayout(header)

        self.slots_box = QVBoxLayout()
        self.slots_box.setSpacing(10)
        root.addLayout(self.slots_box)

        self.hint = QLabel("")
        self.hint.setProperty("role", "caption")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        # Tekshiruv natijasi kadrlar bilan tugmalar ORASIDA: u
        # tugmani bosgandan keyin paydo bo'ladi va o'sha zahoti
        # ko'rinishi kerak.
        #
        # SCROLL MAJBURIY: server 14 tagacha qator qaytaradi va
        # ular kartaga sig'maydi. Scroll bo'lmasa ro'yxat tugmalarni
        # ekrandan itarib chiqarardi — operator natijani ham
        # ko'rmasdi, qayta tekshira ham olmasdi.
        self.checks_box = QVBoxLayout()
        self.checks_box.setSpacing(6)
        self.checks_box.setContentsMargins(0, 0, 0, 0)

        checks_host = QWidget()
        checks_host.setLayout(self.checks_box)

        self.checks_area = QScrollArea()
        self.checks_area.setWidget(checks_host)
        # `WidgetResizable` — ichki vidjet scroll maydoni kengligiga
        # moslashadi. Usiz qatorlar o'z sizeHint'ida qolib, gorizontal
        # scroll paydo bo'lardi.
        self.checks_area.setWidgetResizable(True)
        self.checks_area.setFrameShape(QFrame.Shape.NoFrame)
        self.checks_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.checks_area.setMaximumHeight(_CHECKS_MAX_HEIGHT)
        # Minimum ATAYLAB qo'yilgan: `widgetResizable` bilan scroll
        # maydonining minimal o'lchami ichki vidjetdan hisoblanadi
        # va u past ekranda maydonni siqilishga qo'ymasdi.
        self.checks_area.setMinimumHeight(_CHECKS_MIN_HEIGHT)
        # `Maximum` vertikal siyosati: maydon MAZMUN qadar joy
        # oladi va undan oshmaydi. Standart `Expanding` bo'lsa, bitta
        # qatorli natija ham butun bo'sh joyni egallab, tugmalarni
        # pastga surib yuborardi.
        self.checks_area.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        # Scroll maydoni va uning viewport'i SHAFFOF: aks holda
        # kartaning oq foni ustida kulrang to'rtburchak paydo bo'ladi.
        self.checks_area.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget"
            " { background: transparent; border: none; }"
        )
        self.checks_area.hide()
        # Cho'zilma koeffitsienti 1: bo'sh joy ro'yxat bilan pastdagi
        # oraliq orasida bo'linadi, ya'ni katta ekranda ko'proq qator
        # ko'rinadi. `Maximum` siyosati uni `_CHECKS_MAX_HEIGHT` dan
        # oshirmaydi - aks holda ikkita kamerali mashinada ro'yxat
        # butun kartani egallardi.
        root.addWidget(self.checks_area, 1)

        root.addStretch()

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        self.action_btn = QPushButton("Kamerani ishga tushirish")
        self.action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_btn.setStyleSheet(tonal_button_style(46))
        self.action_btn.clicked.connect(self._toggle_preview)
        self.action_btn.setEnabled(False)
        buttons.addWidget(self.action_btn, 1)

        self.check_btn = QPushButton("Hammasini tekshirish")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.setStyleSheet(tonal_button_style(46))
        self.check_btn.setToolTip(
            "Barcha kameralarni o'lchab, natijani serverga yuboradi va uning "
            "xulosasini ko'rsatadi. Har bir kamerani ALOHIDA tekshirish uchun "
            "kadr ostidagi tugmadan foydalaning"
        )
        self.check_btn.clicked.connect(lambda: self.run_check())
        self.check_btn.setEnabled(False)
        buttons.addWidget(self.check_btn, 1)

        root.addLayout(buttons)

    # ------------------------------------------------------------------
    # Tashqi API
    # ------------------------------------------------------------------
    def refresh(self, *, handshake_cameras: Optional[list] = None) -> None:
        """
        Sahifa ochilganda yoki yangilanganda chaqiriladi.

        Kamera OCHILMAYDI - faqat ro'yxat yig'iladi. Sabab modul
        docstring'ida.
        """
        self._handshake_cameras = list(handshake_cameras or [])
        self.reload()

    def reload(self) -> None:
        """Serverdagi biriktirishni va lokal qurilmalarni qaytadan o'qiydi."""
        if self._busy:
            return
        self.stop_preview()
        self._warmup.stop()
        self._checking = False
        # Eski tekshiruv natijasi YANGILASHDA tozalanadi: u boshqa
        # kameralar tarkibiga tegishli bo'lishi mumkin va uni ekranda
        # qoldirish hozirgi holat deb o'qilardi.
        self._check_result = {}
        self._clear_checks()
        self._busy = True
        if self.reload_btn is not None:
            self.reload_btn.setEnabled(False)
        self.action_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Tekshirish")
        self.hint.setText("Kameralar aniqlanmoqda...")

        worker = ApiWorker(self._repo.camera_config, parent=self)
        worker.succeeded.connect(self._on_config)
        # Serverga yetib bo'lmasa ham lokal kameralarni aniqlaymiz:
        # veb-kamera tarmoqdan mustaqil ishlaydi va operator kamida
        # uni ko'rishi kerak.
        worker.failed.connect(self._on_config_failed)
        self._workers.run(worker)

    def stop_preview(self) -> None:
        """
        Barcha oqimlarni yopadi va qurilmalarni BO'SHATADI.

        Keyingi sahifaga o'tishdan oldin MAJBURIY: FaceID sahifasi
        o'sha veb-kamerani ochadi va Windows'da band qurilma umuman
        ochilmaydi ("Kamera ochilmadi (indeks 0)").
        """
        if not self._previewing:
            return
        self._previewing = False
        self._configured = ()
        self._manager.stop()
        for role, view in self._views.items():
            camera = self._layout_result.get(role)
            view.preview.show_placeholder(
                "Kadr uchun pastdagi tugmani bosing"
                if camera is not None and camera.available
                else "Kamera ishlamaydi"
            )
        self._update_action_label()

    def shutdown(self) -> None:
        self._warmup.stop()
        self.stop_preview()
        self._manager.shutdown()
        self._workers.wait_all(5000)

    @property
    def camera_layout(self) -> camera_roles.CameraLayout:
        return self._layout_result

    @property
    def check_result(self) -> dict:
        """Server baholagan oxirgi tekshiruv (bo'sh - hali o'tkazilmagan)."""
        return dict(self._check_result)

    def set_exam(self, exam_id) -> None:
        """
        Tekshiruv qaysi imtihon siyosati bo'yicha baholanishini
        belgilaydi. Berilmasa global standart ishlatiladi.
        """
        self._exam_id = exam_id

    # ------------------------------------------------------------------
    # Tekshiruv
    # ------------------------------------------------------------------
    def run_check(self, roles=None) -> None:
        """
        Kameralarni o'lchaydi va natijani SERVERGA baholatadi.

        Uch qadam: oqimlarni ochish -> isitish -> o'lchash. Isitish
        MAJBURIY: FPS vaqt oynasi bo'yicha hisoblanadi va endigina
        ochilgan kamerada u haqiqatdan ancha past chiqadi.

        `roles` — faqat shu kameralar o'lchanadi (`None` — hammasi).
        Qolganlarining oldingi natijasi serverdagi suratchada
        saqlanadi va u yerda birlashtiriladi
        (`camera_check._merge_measurements`), ya'ni "faqat yuz
        kamerasini tekshirish" ikkinchisining natijasini
        YO'QOTMAYDI.
        """
        if self._checking or self._busy:
            return
        if not self._layout_result.cameras:
            return

        wanted = tuple(roles) if roles else None
        self._check_roles = wanted
        self._checking = True
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Tekshirilmoqda...")
        for view in self._views.values():
            view.set_busy(True, mine=wanted is None or view.role in wanted)
        self._clear_checks()
        self.hint.setText("Kamera ishga tushirilmoqda...")

        # FAQAT KERAKLI kamera ochiladi: ikkinchisini bekorga ochish
        # operatorni ~2 soniya kutishga majbur qilardi va qurilmani
        # band qilib turardi.
        self._start_preview(roles=wanted)
        self._warmup.start(_WARMUP_MS)

    def _collect_measurements(self) -> None:
        """Isitish tugadi - o'lchov FON thread'ida olinadi."""
        self.hint.setText("O'lchanmoqda...")
        worker = ApiWorker(
            camera_measure.measure_all,
            self._manager,
            self._layout_result,
            roles=self._check_roles,
            parent=self,
        )
        worker.succeeded.connect(self._send_measurements)
        worker.failed.connect(self._on_check_failed)
        self._workers.run(worker)
    def _send_measurements(self, cameras) -> None:
        self.hint.setText("Server baholamoqda...")
        worker = ApiWorker(
            self._repo.camera_check,
            cameras=cameras or [],
            exam_id=self._exam_id,
            parent=self,
        )
        worker.succeeded.connect(self._on_check_done)
        worker.failed.connect(self._on_check_failed)
        self._workers.run(worker)

    def _on_check_done(self, result) -> None:
        self._checking = False
        self._check_roles = None
        self._check_result = result or {}
        self.check_btn.setEnabled(True)
        self.check_btn.setText("Hammasini qayta tekshirish")
        for view in self._views.values():
            view.set_busy(False)
        self._render_checks(self._check_result)
        self.check_completed.emit(self._check_result)

    def _on_check_failed(self, message: str, code: str) -> None:
        self._checking = False
        self._check_roles = None
        self.check_btn.setEnabled(True)
        self.check_btn.setText("Hammasini tekshirish")
        for view in self._views.values():
            view.set_busy(False)
        # Natija TOZALANADI: eski tekshiruvni ekranda qoldirish uni
        # hozirgi holat deb o'qishga majbur qilardi.
        self._check_result = {}
        self._clear_checks()
        self._update_slot_states()
        self.hint.setText("Tekshirib bo'lmadi: {}".format(message))
        log.warning("Kamera tekshiruvi muvaffaqiyatsiz (%s): %s", code or "-", message)
        self.check_completed.emit({})

    def _update_slot_states(self) -> None:
        """Har bir kadr ostidagi nishonni server xulosasiga moslaydi."""
        summaries = (self._check_result or {}).get("cameras") or {}
        for view in self._views.values():
            view.set_check_state(summaries.get(view.role) or {} if view.role else {})

    def _render_checks(self, result: dict) -> None:
        self._clear_checks()
        self._update_slot_states()
        checks = result.get("checks") or []
        for index, check in enumerate(checks):
            self.checks_box.addWidget(CheckRow(check, index))
        # Bo'sh scroll maydoni YASHIRILADI: aks holda tekshiruvdan
        # oldin kartada tushuntirib bo'lmaydigan bo'sh oraliq turardi.
        self.checks_area.setVisible(bool(checks))

        status = result.get("status", "ready")
        if result.get("can_start"):
            self.hint.setText(
                "Tekshiruvdan o'tdi."
                if status == "ready"
                else "Tekshiruvdan o'tdi — ogohlantirishlar bilan."
            )
        else:
            self.hint.setText("Tekshiruvdan o'tmadi — imtihonni boshlab bo'lmaydi.")

    # ------------------------------------------------------------------
    # Ma'lumot yig'ish
    # ------------------------------------------------------------------
    def _on_config(self, payload) -> None:
        # Server BINODAGI kameralar ro'yxatini beradi (rollar emas).
        # Ro'yxat handshake'dagidan yangiroq: u shu sahifa ochilganda
        # so'raladi, handshake esa login paytida bo'lgan.
        cameras = (payload or {}).get("cameras")
        if cameras:
            self._handshake_cameras = list(cameras)
        self._manager.discover_async()

    def _on_config_failed(self, message: str, code: str) -> None:
        log.info("Kamera konfiguratsiyasi olinmadi (%s): %s", code or "-", message)
        # Handshake ro'yxati QOLADI: u ham shu binodagi kameralar va
        # tarmoq xatosi tufayli IP kameralarni ro'yxatdan tushirib
        # qoldirish "kamera yo'qoldi" degan yolg'on xabar bo'lardi.
        self._manager.discover_async()

    def _on_devices(self, _devices: list) -> None:
        """Lokal qurilmalar aniqlandi - endi rollarni hisoblash mumkin."""
        self._busy = False
        if self.reload_btn is not None:
            self.reload_btn.setEnabled(True)

        layout = camera_roles.resolve(
            handshake_cameras=self._handshake_cameras,
            discovered=self._manager.discovered,
        )
        # OPERATOR TANLOVI YANGILASHDAN KEYIN HAM SAQLANADI. Qurilmalar
        # qaytadan aniqlanadi va zaxira qoida rollarni noldan
        # taqsimlaydi - tanlov esa qurilmaning o'ziga tegishli.
        # Uni tiklamaslik operatorni har "Yangilash" dan keyin
        # kameralarni qaytadan almashtirishga majbur qilardi.
        if self._choices:
            layout = camera_roles.apply_choices(layout, self._choices)

        self._layout_result = layout
        self._render()
        self.layout_resolved.emit(self._layout_result)

    def _on_role_chosen(self, key: str, purpose: str) -> None:
        """
        Operator kameraga vazifa berdi: yuz / obyekt / ishlatilmaydi.

        OQIM VA TEKSHIRUV BEKOR QILINADI: oqimlar rol bo'yicha
        ochilgan (`CameraManager` slotlari) va rollar almashgach
        ular boshqa kameraga tegishli bo'lib qoladi. Eski tekshiruv
        natijasi ham endi boshqa kameraga tegishli - uni ekranda
        qoldirish "birlamchi kamera tekshiruvdan o'tdi" degan
        YOLG'ON xabar bo'lardi.
        """
        updated = camera_roles.assign(self._layout_result, key=key, purpose=purpose)
        if updated is self._layout_result:
            return

        self._choices = updated.choices()
        self.stop_preview()
        self._check_result = {}
        self._clear_checks()

        self._layout_result = updated
        self._render()
        self.layout_resolved.emit(self._layout_result)
        self.check_completed.emit({})
        log.info(
            "Operator vazifalarni o'zgartirdi: yuz = %s, obyekt = %s",
            self._layout_result.face.label if self._layout_result.face else "-",
            self._layout_result.objects.label if self._layout_result.objects else "-",
        )

    # ------------------------------------------------------------------
    # Chizish
    # ------------------------------------------------------------------
    def _render(self) -> None:
        self._clear(self.slots_box)
        self._views = {}

        cameras = self._layout_result.cameras
        if not cameras:
            empty = QLabel(
                "Kamera topilmadi. Veb-kamera ulanganini tekshiring yoki "
                "administratordan IP kamera biriktirishni so'rang."
            )
            empty.setProperty("role", "caption")
            empty.setWordWrap(True)
            self.slots_box.addWidget(empty)
            self.hint.setText("")
            self.action_btn.setEnabled(False)
            self.check_btn.setEnabled(False)
            self._update_action_label()
            return

        can_choose = self._layout_result.can_choose
        # KARTALAR QURILMA TARTIBIDA, ROL TARTIBIDA EMAS.
        #
        # Ilgari ular `layout.cameras` tartibida chizilardi, u esa
        # ROL bo'yicha tuzilgan (birinchi - yuz kamerasi). Operator
        # o'ng kartada "Yuz tekshiruvi" ni tanlashi bilan o'sha
        # kamera birinchi bo'lib qolar va karta CHAPGA sakrardi:
        # ekranda bu "tanlov teskari ishladi va kameralarning nomi
        # almashib ketdi" bo'lib ko'rinardi, holbuki taqsimot
        # to'g'ri edi. Qurilma tartibi esa o'zgarmaydi - kamera
        # qayerda turgan bo'lsa, o'sha yerda qoladi.
        cameras = _by_device(cameras)
        # Kartalar IKKITADAN bitta qatorga. Har bir qator ALOHIDA
        # vidjet (ichma-ich layout emas): `_clear()` faqat vidjetlarni
        # oladi va bo'sh layout undan qutulib qolardi - eski qator
        # yangisining ustida ko'rinib turardi.
        for start in range(0, len(cameras), _SLOTS_PER_ROW):
            chunk = cameras[start:start + _SLOTS_PER_ROW]
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            for camera in chunk:
                view = CameraSlotView(
                    camera,
                    height=_PREVIEW_HEIGHT,
                    # Tanlov faqat ikkita va undan ko'p ishlaydigan
                    # kamerada (`CameraLayout.can_choose`).
                    can_choose=can_choose and camera.available,
                    can_spare=len(self._layout_result.usable) >= 2,
                )
                view.role_chosen.connect(self._on_role_chosen)
                view.check_requested.connect(
                    lambda role: self.run_check(roles=(role,))
                )
                self._views[camera.slot_id] = view
                # Teng cho'zilma - kartalar aynan yarmidan.
                row_layout.addWidget(view, 1)
            # Qator to'lmagan bo'lsa bo'sh joy qoldiriladi, LEKIN
            # faqat kamera bittadan ko'p bo'lganda. Yolg'iz kamera
            # butun kenglikni oladi: uning yonida tenglashtiradigan
            # hech narsa yo'q va yarim kenglik kadrni bekorga
            # kichraytirardi.
            if len(cameras) > 1:
                for _ in range(_SLOTS_PER_ROW - len(chunk)):
                    row_layout.addStretch(1)
            self.slots_box.addWidget(row)

        self.hint.setText(self._hint_text())
        self._update_slot_states()
        usable = bool(self._layout_result.usable)
        self.action_btn.setEnabled(usable)
        # Tekshirish ishlaydigan kamerasiz ham ma'noga ega: server
        # "kamera topilmadi" degan RASMIY xulosani qaytaradi va u
        # `proctoring/start/` da to'siq bo'lib ishlaydi. Aks holda
        # operator "nega boshlanmadi?" degan savol bilan qolardi.
        self.check_btn.setEnabled(bool(self._layout_result.cameras))
        self._update_action_label()

    def _update_action_label(self) -> None:
        plural = len(self._layout_result.usable) > 1
        if self._previewing:
            self.action_btn.setText(
                "Kameralarni to'xtatish" if plural else "Kamerani to'xtatish"
            )
        else:
            self.action_btn.setText(
                "Kameralarni ishga tushirish" if plural else "Kamerani ishga tushirish"
            )

    def _hint_text(self) -> str:
        """
        Rollar QAYERDAN kelganini aytadi.

        Bu qator ixtiyoriy emas: taxmin qilingan rol noto'g'ri
        bo'lishi mumkin (kamera boshqa tomonga qaragan) va uni faqat
        odam tuzatadi. Operator taxmin ekanini bilmasa, tuzatish
        kerakligi ham hech qachon ma'lum bo'lmaydi.
        """
        layout = self._layout_result
        if not layout.cameras:
            return ""
        usable = len(layout.usable)
        if usable >= 3:
            return (
                "{} ta kamera: ikkitasiga vazifa beriladi, qolgani ishlatilmaydi. "
                "Kadrlarni solishtirib, har biriga kadr ustidan vazifa tanlang. "
                "Tekshirish uchun yuz kamerasi yetarli.".format(usable)
            )
        if usable >= 2:
            # TAVSIYA HAM SHU YERDA: tekshiruv uchun yuz kamerasi
            # yetadi. Aynan u shaxsni aniqlaydi va uning nosozligi
            # imtihonni to'xtatadi; ikkinchisi esa siyosat talab
            # qilsagina majburiy (`secondary_required`).
            chosen = "Rollarni operator tanladi." if layout.chosen_by_operator else (
                "Rollar avtomatik taqsimlandi — kadrlarni solishtirib tekshiring."
            )
            return (
                "{} Vazifani almashtirish uchun kadr ustidagi tugmalardan "
                "foydalaning. Tekshirish uchun yuz kamerasi yetarli.".format(chosen)
            )
        if usable == 1:
            return "Bitta kamera: yuz tekshiruvi. Obyekt aniqlash uchun ikkinchisi kerak."
        return "Ishlaydigan kamera yo'q — yuz tekshiruvi bajarilmaydi."

    def _clear_checks(self) -> None:
        """Natijalar ro'yxatini bo'shatadi va scroll maydonini yashiradi."""
        self._clear(self.checks_box)
        self.checks_area.hide()

    @staticmethod
    def _clear(box) -> None:
        """
        Layout'ni bo'shatadi.

        `setParent(None)` MAJBURIY va u `deleteLater()` ni
        almashtirmaydi, to'ldiradi:

          * `takeAt()` vidjetni faqat LAYOUTDAN oladi — u ota
            vidjetning bolasi bo'lib qoladi va oxirgi geometriyasida
            KO'RINIB turadi;
          * `deleteLater()` esa o'chirishni hodisa navbatiga qo'yadi,
            ya'ni u faqat keyingi siklda bajariladi.

        Natijada ro'yxat yangilanganda eski qatorlar yangilarining
        USTIDA qolib ketardi. `setParent(None)` vidjetni o'sha
        zahoti ekrandan oladi, `deleteLater()` esa xotirani
        keyinroq bo'shatadi (darhol `del` qilish xavfli: signal
        qayta ishlanayotgan bo'lishi mumkin).
        """
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # ------------------------------------------------------------------
    # Oldindan ko'rish
    # ------------------------------------------------------------------
    def _toggle_preview(self) -> None:
        if self._previewing:
            self.stop_preview()
        else:
            self._start_preview()

    def _start_preview(self, roles=None) -> None:
        """
        Oqimlarni ochadi.

        `roles` — faqat shu rollar (`None` — hammasi). Bitta kamerani
        tekshirishda ikkinchisini ochish bekorga ~2 soniya kutish va
        qurilmani band qilish bo'lardi.

        QAYTA SOZLASH FAQAT KERAK BO'LGANDA. `CameraManager.configure()`
        ishlab turgan BARCHA oqimlarni to'xtatadi (slotlar
        almashtirilishi mumkin), ya'ni uni har chaqiruvda bajarish
        allaqachon isigan kamerani qaytadan ochib, o'lchovni buzardi:
        FPS vaqt oynasi noldan boshlanadi va tekshiruv soxta "FPS
        past" beradi.
        """
        usable = [
            camera
            for camera in self._layout_result.usable
            if roles is None or camera.role in roles
        ]
        if not usable:
            return

        # Slotlar tarkibi: rol -> qurilma. Rollar almashtirilsa yoki
        # kamera qo'shilsa/yo'qolsa u o'zgaradi va manager qaytadan
        # sozlanishi SHART.
        signature = tuple(
            sorted((camera.slot_id, camera.key) for camera in self._layout_result.cameras)
        )
        if not self._previewing or signature != self._configured:
            self._manager.configure(
                # HAMMA qurilma - zaxiradagisi ham: operator uchinchi
                # kamerani (masalan binodagi IP kamerani) ko'rib turib
                # unga vazifa berishi kerak.
                self._layout_result.preview_slots(),
                # IP kamera uchun kredensial SHU YERDA so'raladi va hech
                # qayerda saqlanmaydi: manager uni oqim ochilayotgan
                # paytda chaqiradi va natijani tashlab yuboradi.
                stream_url_provider=self._repo.camera_stream,
            )
            self._configured = signature
            # Sozlash barcha oqimlarni to'xtatdi — ochilmaydigan
            # kadrlarda oxirgi tasvir qolib ketmasligi kerak, u
            # "kamera ishlab turibdi" degan yolg'on xabar bo'lardi.
            for slot_id, view in self._views.items():
                if slot_id not in {camera.slot_id for camera in usable}:
                    view.preview.show_placeholder("Kadr uchun pastdagi tugmani bosing")

        self._previewing = True
        self._update_action_label()

        for camera in usable:
            view = self._views.get(camera.slot_id)
            if view is not None and self._manager.stream(camera.slot_id) is None:
                view.preview.show_placeholder("Kamera ochilmoqda...")

        # So'ralgan kameralar BIR VAQTDA ochiladi: ular imtihon
        # davomida ham birga ishlaydi va oldindan ko'rish aynan shu
        # holatni ko'rsatishi kerak. Navbat bilan ochish "ikkinchisi
        # ham ishlaydi" degan xulosani asossiz qoldirardi.
        self._manager.start([camera.slot_id for camera in usable])

    def _on_frame(self, role: str, frame) -> None:
        if not self._previewing:
            return
        view = self._views.get(role)
        if view is not None:
            view.preview.show_frame(frame)

    def _on_camera_state(self, role: str, state: str) -> None:
        if not self._previewing:
            return
        view = self._views.get(role)
        if view is None:
            return
        if state in ("failed", "reconnecting"):
            stream = self._manager.stream(role)
            reason = stream.health.last_error if stream else ""
            view.preview.show_placeholder(reason or "Kameradan kadr kelmayapti")
        elif state == "opening":
            view.preview.show_placeholder("Kamera ochilmoqda...")
