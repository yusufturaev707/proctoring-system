"""
3-SAHIFA - JSHSHIR bo'yicha talabgorni tekshirish.

Backend `/client/candidate/lookup/` tanlangan imtihonning O'Z
platformasiga boradi (`Exam.site_url` + shifrlangan sarlavha) va
javobni tushunarli shaklga keltirib qaytaradi.

CLIENT PLATFORMAGA O'ZI MUROJAAT QILMAYDI. U manzilni ham,
kredensialni ham bilmaydi — bularning hammasi serverda
(`integrations/exam_site.py`). Bu sahifa faqat natijani
ko'rsatadi.

Bu tizimdagi ENG NOZIK endpoint: JSHSHIR strukturasi ma'lum, ya'ni
chegarasiz u fuqarolar ismini qidirish servisiga aylanadi. Shuning
uchun backendda ikki xil throttle bor va client ularni hurmat qiladi:
so'rov ketayotganda tugma bloklanadi, 429 javobi esa alohida
ko'rsatiladi ("biroz kutib qayta urining").

Javobda TEST HAVOLASI (`test_link`) client'ga BERILMAYDI - u FaceID
va operator tasdig'idan keyin, 5-sahifada `exam/access/` orqali
olinadi. Sabab backend `issue_exam_access` docstring'ida: bu
qaytib bo'lmaydigan nuqta va undan oldin shaxs tasdiqlanishi
shart. Havolani shu yerda berish FaceID'ni butunlay chetlab
o'tish imkonini berardi.

JOYLASHUV: BITTA MARKAZIY USTUN.

Ilgari ekran ikki ustunga bo'lingan edi (chapda forma, o'ngda
natija) va bu sahifaning vazifasiga mos kelmasdi. Bu yerda operator
BITTA ish qiladi va u ketma-ket: raqamni kiritadi -> natijani
o'qiydi -> davom etadi. Ikki ustunda esa ko'z chapdan o'ngga
sakrardi va ekranning yarmi talabgor topilmaguncha bo'sh turardi.
Markaziy ustunda natija formaning OSTIDA ochiladi, ya'ni o'qish
tartibi harakat tartibi bilan bir xil.

SARLAVHADA XODIM ISMI YO'Q va bu ataylab. Operator kim ekanini
o'zi biladi; ekranda esa har doim ko'rinishi kerak bo'lgan narsa
boshqa - QAYSI TEST topshirilyapti. Noto'g'ri testni tanlab qo'yish
bu oqimdagi eng qimmat xato (talabgor boshqa imtihonga kiritiladi)
va uni faqat sarlavhadagi nom ushlaydi.

"ORQAGA" VA "CHIQISH" TUGMALARI HAM YO'Q. Bu yerda ekran oldida
talabgor turadi va sahifada faqat bitta yo'l bo'lishi kerak.
Navigatsiya yo'qolmaydi: Ctrl+Q dialogi "Imtihon tanlashga
qaytish" ni taklif qiladi (`MainWindow._back_action`) va u parol
bilan himoyalangan - ya'ni sahifani talabgor emas, operator
almashtiradi.
"""

from __future__ import annotations

import base64
import binascii
import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.app_state import AppState, Candidate
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import (
    COLORS,
    badge_style,
    code_field_style,
    primary_button_style,
    surface_container_style,
)
from ui.widgets.camera_view import PhotoView
from ui.widgets.header import PageHeader, ip_chip_hints
from ui.widgets.indicators import BusyOverlay, Card, MessageBar
from ui.widgets.seat_notice import SEAT_CODES, SeatNotice

log = logging.getLogger(__name__)

PINFL_LENGTH = 14

#: Markaziy ustunning maksimal kengligi.
#:
#: Cheklov MAJBURIY: 1920 px ekranda cho'zilgan karta ichida 14 xonali
#: raqam va uch qatorli natija adashib qoladi - ko'z bir chetidan
#: ikkinchisiga yuguradi. Bu qiymat o'qish uchun qulay satr
#: uzunligiga (~60-70 belgi) mos.
_COLUMN_WIDTH = 620

#: Hujjat rasmi - bu sahifada KICHIK.
#:
#: U bu yerda shaxsni tasdiqlash uchun emas ("to'g'ri odam
#: topildimi?" degan tez qarash uchun): haqiqiy solishtirish keyingi
#: sahifada, jonli kadr yonida bo'ladi va rasm o'sha yerda katta.
_PHOTO_WIDTH = 120
_PHOTO_HEIGHT = 160


class CandidatePage(QWidget):
    """Talabgorni JSHSHIR bo'yicha topish."""

    candidate_ready = pyqtSignal(object)  # Candidate
    #: `MainWindow` ikkalasiga ham ulanadi, lekin bu sahifa ularni
    #: EMITLAMAYDI - yuqoridagi izohga qarang. Signallar oqim
    #: shartnomasi qismi bo'lgani uchun saqlanadi.
    back_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, state: AppState, repo: ProctoringRepository, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        self._workers = WorkerHolder()
        self._setup_ui()

    # ------------------------------------------------------------------
    # Ko'rinish
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 28, 48, 32)
        root.setSpacing(18)

        # Sarlavha: test nomi konstruktorda hali ma'lum emas -
        # u `refresh()` da qo'yiladi.
        self.header = PageHeader(
            "Talabgorni tekshirish",
            "2-qadam · JSHSHIR bo'yicha qidirish",
            step=2,
            show_back=False,
            show_logout=False,
            chips=("region", "zone", "ip"),
        )
        root.addWidget(self.header)

        # Ustun MARKAZDA. Tepadagi cho'zilma pastdagidan KICHIK:
        # geometrik markaz ko'zga pastroq ko'rinadi, shuning uchun
        # blok biroz tepaga suriladi (optik markazlashtirish).
        root.addStretch(2)

        center = QHBoxLayout()
        center.addStretch(1)

        column = QWidget()
        # Kenglik QAT'IY, maksimal EMAS: maksimal bo'lsa ustun o'z
        # mazmuniga qarab torayadi va natija kartasi ochilganda
        # qidiruv kartasi ham "kengayib" ketardi - ekranda hech narsa
        # o'z joyida turmasdi.
        column.setFixedWidth(_COLUMN_WIDTH)
        self._column = QVBoxLayout(column)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(16)
        self._column.addWidget(self._build_search_card())
        # Bron bo'yicha rad javobi — natija kartasining O'RNIDA, ular
        # hech qachon birga ko'rinmaydi.
        self.seat_notice = SeatNotice()
        self._column.addWidget(self.seat_notice)
        self._column.addWidget(self._build_result_card())

        center.addWidget(column)
        center.addStretch(1)
        root.addLayout(center)

        root.addStretch(3)

        self.result_card.setVisible(False)
        self.overlay = BusyOverlay(self)

    def _build_search_card(self) -> Card:
        card = Card()

        title = QLabel("JSHSHIR")
        title.setProperty("role", "value")
        card.body.addWidget(title)

        caption = QLabel("Talabgorning 14 xonali identifikatorini kiriting")
        caption.setProperty("role", "caption")
        card.body.addWidget(caption)
        card.body.addSpacing(6)

        self.pinfl_input = QLineEdit()
        self.pinfl_input.setPlaceholderText("••••••••••••••")
        self.pinfl_input.setMaxLength(PINFL_LENGTH)
        self.pinfl_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Tozalash tugmasi maydonning ICHIDA: xato kiritilgan raqamni
        # 14 marta Backspace bosib o'chirish operatorning har
        # talabgorda takrorlanadigan ishi bo'lardi.
        self.pinfl_input.setClearButtonEnabled(True)
        self.pinfl_input.setStyleSheet(code_field_style())
        self.pinfl_input.textChanged.connect(self._on_pinfl_changed)
        self.pinfl_input.returnPressed.connect(self._on_lookup)
        card.body.addWidget(self.pinfl_input)

        helper = QHBoxLayout()
        helper.setContentsMargins(4, 0, 4, 0)
        self.hint_label = QLabel("Enter tugmasi bilan ham qidirish mumkin")
        self.hint_label.setProperty("role", "caption")
        helper.addWidget(self.hint_label)
        helper.addStretch(1)
        # Hisoblagich rangdan MUSTAQIL signal: maydon ramkasi
        # yashil bo'lishini ko'rmagan operator ham nechta raqam
        # qolganini biladi.
        self.counter_label = QLabel()
        self.counter_label.setProperty("role", "caption")
        helper.addWidget(self.counter_label)
        card.body.addLayout(helper)

        card.body.addSpacing(4)
        self.lookup_btn = QPushButton("TEKSHIRISH")
        self.lookup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lookup_btn.setStyleSheet(primary_button_style(52))
        self.lookup_btn.setEnabled(False)
        self.lookup_btn.clicked.connect(self._on_lookup)
        card.body.addWidget(self.lookup_btn)

        self.message = MessageBar()
        card.body.addWidget(self.message)

        self._update_pinfl_state("")
        return card

    def _build_result_card(self) -> Card:
        self.result_card = Card()
        row = QHBoxLayout()
        row.setSpacing(18)

        self.photo = PhotoView(width=_PHOTO_WIDTH, height=_PHOTO_HEIGHT)
        row.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(4)

        self.name_label = QLabel("-")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.name_label.setStyleSheet(
            "font-size: 21px; font-weight: 700; color: {};".format(COLORS["text"])
        )
        info.addWidget(self.name_label)

        # Platforma xabari NOM OSTIDA: u javobning eng muhim qismi
        # ("Testga ruxsat!") va identifikatorlardan oldin o'qilishi
        # kerak.
        self.platform_label = QLabel("")
        self.platform_label.setWordWrap(True)
        self.platform_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: {};".format(COLORS["primary_dark"])
        )
        self.platform_label.setVisible(False)
        info.addWidget(self.platform_label)

        info.addSpacing(6)
        meta = QHBoxLayout()
        meta.setSpacing(22)
        self._value_labels: dict = {}
        self._meta_captions: dict = {}
        # Uchta qiymat YONMA-YON: ular qisqa va vertikal ro'yxatda
        # kartani ikki barobar uzaytirardi. Yorliq qiymat USTIDA -
        # ko'z avval nima ekanini, keyin qiymatni o'qiydi.
        #
        # Maydonlar platformaning javobiga MOS: u F.I.Sh. bermaydi,
        # faqat identifikatorlar beradi (`data.id`, `data.abitur_id`).
        # Operator nosozlikda administratorga aynan shu raqamlarni
        # aytadi.
        for key, caption in (
            ("masked_pinfl", "JSHSHIR"),
            ("external_candidate_id", "Platforma ID"),
            ("abitur_id", "Abituriyent ID"),
        ):
            meta.addLayout(self._meta_cell(key, caption))
        meta.addStretch(1)
        info.addLayout(meta)

        info.addSpacing(10)
        self.reference_badge = QLabel("")
        self.reference_badge.setFixedHeight(24)
        info.addWidget(self.reference_badge, 0, Qt.AlignmentFlag.AlignLeft)
        info.addStretch(1)

        row.addLayout(info, 1)
        self.result_card.body.addLayout(row)

        self.result_card.body.addSpacing(14)
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        info_row.addWidget(self._build_seat_panel(), 1)
        info_row.addWidget(self._build_duration_panel(), 1)
        self.result_card.body.addLayout(info_row)

        self.result_card.body.addSpacing(10)
        self.next_btn = QPushButton("YUZNI TEKSHIRISH")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.setStyleSheet(primary_button_style(52))
        self.next_btn.clicked.connect(self._on_next)
        self.result_card.body.addWidget(self.next_btn)
        return self.result_card

    def _build_duration_panel(self) -> QFrame:
        """
        Test vaqti - IDENTIFIKATORLAR QATORIDA EMAS, alohida blokda.

        Sabab auditoriyada: raqamlar qatorini operator o'qiydi, test
        vaqtini esa TALABGOR so'raydi va u ekranga uzoqdan qaraydi.
        Kichik katakda, "Abituriyent ID" yonida turgan "3 soat"
        yozuvi shu savolga javob bermasdi - u boshqa ma'lumot
        turkumiga tegishli.
        """
        panel = QFrame()
        panel.setObjectName("durationPanel")
        # "high" tonal: bu karta ichidagi YAGONA ta'kidlangan blok va
        # u ko'zga birinchi tashlanishi kerak.
        panel.setStyleSheet(surface_container_style("durationPanel", tone="high"))
        box = QHBoxLayout(panel)
        box.setContentsMargins(18, 12, 18, 12)
        box.setSpacing(12)

        caption = QLabel("TESTGA AJRATILGAN VAQT")
        caption.setStyleSheet(
            "font-size: 11px; font-weight: 700; letter-spacing: 0.6px; "
            "background: transparent; color: {};".format(COLORS["primary_dark"])
        )
        box.addWidget(caption, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addStretch(1)

        self.duration_value = QLabel("-")
        self.duration_value.setStyleSheet(
            "font-size: 22px; font-weight: 700; background: transparent; "
            "color: {};".format(COLORS["primary_deep"])
        )
        box.addWidget(self.duration_value, 0, Qt.AlignmentFlag.AlignVCenter)

        self.duration_panel = panel
        panel.setVisible(False)
        return panel

    def _build_seat_panel(self) -> QFrame:
        """
        Bron bo'yicha joy TASDIQLANDI — vaqt paneli bilan yonma-yon.

        Faqat bron yuritiladigan sessiyada ko'rinadi. U "to'g'ri stoldami?"
        degan savolga ijobiy javob va raqam: operator talabgorga "siz
        №12 dasiz" deb aytadi.
        """
        panel = QFrame()
        panel.setObjectName("seatPanel")
        panel.setStyleSheet(surface_container_style("seatPanel", tone="high"))
        box = QHBoxLayout(panel)
        box.setContentsMargins(18, 12, 18, 12)
        box.setSpacing(12)

        caption = QLabel("JOY TASDIQLANDI")
        caption.setStyleSheet(
            "font-size: 11px; font-weight: 700; letter-spacing: 0.6px; "
            "background: transparent; color: {};".format(COLORS["primary_dark"])
        )
        box.addWidget(caption, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addStretch(1)

        self.seat_value = QLabel("-")
        self.seat_value.setStyleSheet(
            "font-size: 22px; font-weight: 700; background: transparent; "
            "color: {};".format(COLORS["primary_deep"])
        )
        box.addWidget(self.seat_value, 0, Qt.AlignmentFlag.AlignVCenter)

        self.seat_panel = panel
        panel.setVisible(False)
        return panel

    def _apply_seat(self, candidate: Candidate) -> None:
        seat = candidate.seat or {}
        number = seat.get("number")
        self.seat_value.setText("№{}".format(number) if number else seat.get("inventory_code", ""))
        self.seat_panel.setToolTip(
            " · ".join(part for part in (
                seat.get("label"), seat.get("zone_name"), seat.get("region_name")
            ) if part)
        )
        self.seat_panel.setVisible(bool(candidate.seat))

    def _apply_duration(self, candidate: Candidate) -> None:
        """
        Vaqt kelmasa BLOK UMUMAN KO'RSATILMAYDI.

        "0 daqiqa" yoki bo'sh blok yolg'on bo'lardi: platforma
        qiymatni bermagan bo'lishi mumkin (eski o'rnatish) va bu
        nosozlik emas.
        """
        label = candidate.duration_label
        self.duration_value.setText(label)
        # Xom qiymat tooltip'da: operator platforma bilan bahsda
        # aynan shu sonni aytadi.
        self.duration_panel.setToolTip(
            "Platforma bergan qiymat: {} daqiqa".format(candidate.duration_minutes)
            if label
            else ""
        )
        self.duration_panel.setVisible(bool(label))

    def _meta_cell(self, key: str, caption: str) -> QVBoxLayout:
        cell = QVBoxLayout()
        cell.setSpacing(1)
        label = QLabel(caption)
        label.setStyleSheet(
            "font-size: 11px; font-weight: 700; letter-spacing: 0.6px; color: {};".format(
                COLORS["text_muted"]
            )
        )
        cell.addWidget(label)
        value = QLabel("-")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: {};".format(COLORS["text"])
        )
        cell.addWidget(value)
        self._value_labels[key] = value
        # Yorliq ham saqlanadi: katakni yashirish uchun IKKALASINI
        # yashirish kerak, aks holda ekranda qiymatsiz sarlavha
        # qolib ketadi.
        self._meta_captions[key] = label
        return cell

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Yangi talabgor uchun sahifani tozalaydi."""
        exam = self._state.selected_exam
        staff = self._state.staff
        device = self._state.device

        # Sarlavha - TEST nomi. Xodim ismi ataylab yo'q (modul
        # izohiga qarang).
        self.header.set_title(exam.name if exam else "Test tanlanmagan")
        self.header.set_seat(device)
        tooltips, captions = ip_chip_hints(self._state.machine.get("ips"))
        self.header.set_chips(
            region=staff.region_name if staff else "",
            zone=device.zone_name,
            # ASOSIY manzil (marshrut tanlagani); bir nechta bo'lsa
            # to'liq ro'yxat tooltip'da.
            ip=self._state.machine.get("ip", ""),
            tooltips=tooltips,
            captions=captions,
        )

        self.pinfl_input.clear()
        self.message.clear_message()
        self.result_card.setVisible(False)
        self.seat_notice.hide()
        self.pinfl_input.setFocus()

    def show_finish_notice(self, result: dict) -> None:
        """
        Oldingi imtihon yakuni natijasi — joy bo'shadimi.

        Uch holat va operator har birida boshqa ish qiladi:

            joy bo'shadi     -> keyingi talabgorni kiritadi;
            server javobsiz  -> joy BAND qolgan bo'lishi mumkin:
                                administrator panelda bo'shatadi, aks
                                holda keyingi talabgor bu stolda
                                `wrong_computer` oladi;
            bron yo'q edi    -> xabar kerak emas (bron yuritilmaydi).
        """
        if result.get("error"):
            self.message.show_message(
                "Imtihon yakuni serverga yetmadi — kompyuter band bo‘lib qolgan bo‘lishi "
                "mumkin. Keyingi talabgor kira olmasa, administratorga murojaat qiling.",
                "warning",
            )
            return
        if result.get("seat_released"):
            label = (result.get("seat") or {}).get("label") or "Kompyuter"
            self.message.show_message(
                "Imtihon yakunlandi. «{}» bo‘shatildi — keyingi talabgorni "
                "kiritishingiz mumkin.".format(label),
                "success",
            )

    # ------------------------------------------------------------------
    def _on_pinfl_changed(self, text: str) -> None:
        # Faqat raqam: klaviaturadan tasodifiy belgi tushsa, so'rov
        # backendgacha bormaydi va throttle byudjeti isrof bo'lmaydi.
        digits = "".join(char for char in text if char.isdigit())
        if digits != text:
            self.pinfl_input.blockSignals(True)
            self.pinfl_input.setText(digits)
            self.pinfl_input.blockSignals(False)
        self._update_pinfl_state(digits)

    def _update_pinfl_state(self, digits: str) -> None:
        """
        Hisoblagich, yordamchi matn va tugma - bitta joyda.

        Holat MATN bilan ham aytiladi ("Yana 3 ta raqam"), faqat
        rang bilan emas: maydon fokusda turganda uning ramkasi
        baribir yashil bo'ladi va rang orqali keladigan signal
        o'sha yerda yo'qoladi.
        """
        left = PINFL_LENGTH - len(digits)
        complete = left <= 0
        self.counter_label.setText("{} / {}".format(len(digits), PINFL_LENGTH))
        self.counter_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: {};".format(
                COLORS["primary_dark"] if complete else COLORS["text_muted"]
            )
        )
        if complete:
            self.hint_label.setText("Tayyor — Enter bosing")
        elif digits:
            self.hint_label.setText("Yana {} ta raqam".format(left))
        else:
            self.hint_label.setText("Enter tugmasi bilan ham qidirish mumkin")
        self.lookup_btn.setEnabled(complete)

    def _on_lookup(self) -> None:
        pinfl = self.pinfl_input.text().strip()
        exam = self._state.selected_exam
        if len(pinfl) != PINFL_LENGTH:
            self.message.show_message("JSHSHIR 14 xonali bo'lishi kerak")
            return
        if exam is None:
            self.message.show_message("Avval imtihonni tanlang")
            return

        self._state.reset_flow()
        self.result_card.setVisible(False)
        self.seat_notice.hide()
        self.message.clear_message()
        self.overlay.start("Test platformasidan so'ralmoqda...")
        self.lookup_btn.setEnabled(False)

        worker = ApiWorker(
            self._repo.lookup_candidate,
            pinfl=pinfl,
            exam_id=exam.id,
            # Kompyuter broni shu mashina bilan solishtiriladi.
            mac_address=self._state.machine.get("mac", ""),
            parent=self,
        )
        worker.succeeded.connect(self._on_found)
        worker.failed_details.connect(self._on_failed)
        self._workers.run(worker)

    def _on_found(self, payload) -> None:
        self.overlay.stop()
        self.lookup_btn.setEnabled(True)

        candidate = Candidate.from_api(payload or {})
        self._state.candidate = candidate
        # To'liq JSHSHIR faqat shu yerda ma'lum (operator kiritdi):
        # javobda u niqoblangan holda qaytadi. Mahalliy arxiv fayl
        # nomida to'liq raqamni ishlatadi.
        self._state.pinfl = self.pinfl_input.text().strip()

        self.name_label.setText(candidate.display_name)
        self._value_labels["masked_pinfl"].setText(candidate.masked_pinfl or "-")
        self._value_labels["external_candidate_id"].setText(
            candidate.external_candidate_id or "-"
        )
        self._value_labels["abitur_id"].setText(candidate.abitur_id or "-")

        # JSHSHIR katagi FAQAT ism bo'lganda ko'rinadi: ismsiz holatda
        # u sarlavhada turadi (`display_name`) va katakda takrorlanishi
        # bir xil raqamni ikki marta o'qishga majbur qilardi.
        self._set_meta_visible("masked_pinfl", bool(candidate.full_name))

        # Platformaning O'Z javobi ("Testga ruxsat!") — u yerda
        # ruxsat qarori qabul qilingan va operator aynan shu matnni
        # ko'rishi kerak. Client uni tarjima ham, qisqartirish ham
        # qilmaydi.
        self.platform_label.setText(candidate.platform_message)
        self.platform_label.setVisible(bool(candidate.platform_message))

        self._apply_duration(candidate)
        self._apply_seat(candidate)

        if self._load_photo(candidate):
            self.reference_badge.setText("Hujjat rasmi mavjud")
            self.reference_badge.setStyleSheet(badge_style("success"))
        else:
            # Etalonsiz oqim to'xtamaydi: FaceID bu holatda yuzni QAYD
            # etadi (enrollment), shaxs tasdig'i esa operatorning hujjat
            # tekshiruvi zimmasida qoladi - backend mantig'i ham shunday.
            self.reference_badge.setText("Hujjat rasmi yo'q — operator tasdiqlaydi")
            self.reference_badge.setStyleSheet(badge_style("warning"))

        self.result_card.setVisible(True)
        # "Talabgor topildi" degan xabar ATAYLAB yo'q: natija
        # kartasining o'zi paydo bo'lishi ayni shu narsani aytadi
        # va uni matn bilan takrorlash ekranga ma'lumot qo'shmasdan
        # joy egallardi. Xabar qatori faqat XATO va OGOHLANTIRISH
        # uchun qoladi - ular ko'rinadigan natija bermaydi.
        self.message.clear_message()
        # Fokus KEYINGI qadamga o'tadi: operator natijani o'qib,
        # Enter bilan davom eta oladi va sichqonchaga qo'l uzatmaydi.
        self.next_btn.setFocus()

    def _set_meta_visible(self, key: str, visible: bool) -> None:
        for widget in (self._value_labels.get(key), self._meta_captions.get(key)):
            if widget is not None:
                widget.setVisible(visible)

    def _load_photo(self, candidate: Candidate) -> bool:
        if not candidate.photo_base64:
            self.photo.set_image_bytes(b"")
            return False
        try:
            raw = base64.b64decode(candidate.photo_base64, validate=False)
        except (binascii.Error, ValueError):
            log.warning("Etalon rasm base64 emas")
            self.photo.set_image_bytes(b"")
            return False
        return self.photo.set_image_bytes(raw)

    def _on_failed(self, message: str, code: str, details=None) -> None:
        self.overlay.stop()
        self.lookup_btn.setEnabled(True)
        self.result_card.setVisible(False)
        # Fokus maydonga QAYTADI: xatodan keyingi birinchi harakat -
        # raqamni tuzatish yoki qaytadan kiritish.
        self.pinfl_input.setFocus()
        self.pinfl_input.selectAll()

        # KOMPYUTER BRONI — alohida karta, xabar qatori emas: operatorga
        # "rad etildi" emas, talabgorni QAYSI STOLGA yuborish kerakligi
        # kerak va u yirik raqam bilan ko'rsatiladi (`SeatNotice`).
        if code in SEAT_CODES:
            self.message.clear_message()
            self.seat_notice.show_problem(code, message, details)
            return

        # UCHTA HOLAT UCHTA XIL KO'RSATILADI va bu ataylab: operator
        # har birida boshqa ish qiladi.
        #
        #   not_found      - JSHSHIR platformada yo'q. Birinchi
        #                    harakat: raqamni tekshirish. Bu xato
        #                    EMAS, shuning uchun sariq.
        #   not_eligible   - talabgor topildi, lekin ruxsat yo'q.
        #                    Sabab PLATFORMANIKI ("Imtihon kuni
        #                    emas") va u o'zgartirilmasdan
        #                    ko'rsatiladi - bizning umumiy matnimiz
        #                    operatorga nima qilishni aytmasdi.
        #   qolgani        - haqiqiy xato (tarmoq, server, sozlama).
        if code in ("candidate_not_found", "candidate_not_eligible"):
            self.message.show_message(message, "warning")
            return
        self.message.show_message(message, "error")

    def _on_next(self) -> None:
        if self._state.candidate is None:
            return
        self.candidate_ready.emit(self._state.candidate)

    def shutdown(self) -> None:
        self._workers.wait_all()
