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

SARLAVHADA TASHKILOT NOMI — xodim ismi ham, test nomi ham yo'q
(`header._brand_block`): ekran oldida talabgor turadi.

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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from core.errors import THROTTLE_SCOPES, throttle_scope
from proctoring.policy import camera_check_required
from services.app_state import AppState, Candidate
from services.network_status import network_status
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import (
    COLORS,
    badge_style,
    code_field_style,
    primary_button_style,
    surface_container_style,
)
from ui.dialogs.offer_dialog import OfferDialog
from ui.widgets.camera_view import PhotoView
from ui.widgets.header import PageHeader, ip_chip_hints
from ui.widgets.indicators import BusyOverlay, Card
from ui.widgets.md3 import (
    IconBadge,
    RippleButton,
    SegmentProgress,
    StatusIcon,
    elevate,
    reveal,
    shake,
)
from ui.widgets.notice import Notice
from ui.widgets.seat_notice import SEAT_CODES, SeatNotice

log = logging.getLogger(__name__)

PINFL_LENGTH = 14

#: Markaziy ustunning maksimal kengligi.
#:
#: Cheklov MAJBURIY: 1920 px ekranda cho'zilgan karta ichida 14 xonali
#: raqam va uch qatorli natija adashib qoladi - ko'z bir chetidan
#: ikkinchisiga yuguradi. Bu qiymat o'qish uchun qulay satr
#: uzunligiga (~60-70 belgi) mos.
_COLUMN_WIDTH = 640

#: Hujjat rasmi - bu sahifada KICHIK.
#:
#: U bu yerda shaxsni tasdiqlash uchun emas ("to'g'ri odam
#: topildimi?" degan tez qarash uchun): haqiqiy solishtirish keyingi
#: sahifada, jonli kadr yonida bo'ladi va rasm o'sha yerda katta.
_PHOTO_WIDTH = 120
_PHOTO_HEIGHT = 160

#: Kamera tekshiruvi muddatidan shuncha soniya QOLGANDA ham to'xtatamiz.
#:
#: JSHSHIR qidiruvidan `proctoring/start/` gacha yuz tekshiruvi va
#: operatorning hujjat tasdig'i bor - odatda 1-3 daqiqa, sekin
#: operatorda ko'proq. Muddat shu oraliqda tugasa talabgor yana yuzdan
#: o'tib bo'lgach rad etilardi - aynan shu holatni yo'qotish uchun
#: tekshiruv bu yerda turibdi.
_CHECK_MARGIN_S = 10 * 60

#: Kutish paytida muddat qanchalik tez-tez tekshiriladi (ms).
#:
#: Operator keyingi talabgorni soatlab kutishi mumkin va muddat aynan
#: o'sha paytda tugaydi - ogohlantirish talabgor kelishidan OLDIN
#: ekranda turishi kerak, "TEKSHIRISH" bosilgandagina emas.
_CHECK_POLL_MS = 30_000

#: Xato kodi -> xabar sarlavhasi ("nima bo'ldi"). Matn serverniki.
_ERROR_TITLES = {
    "network": "Server bilan aloqa yo‘q",
    "server_unavailable": "Server vaqtincha javob bermayapti",
    "throttled": "Juda ko‘p so‘rov",
    "exam_schedule_missing": "Test sessiyasi topilmadi",
    "exam_not_open": "Kirish oynasi yopiq",
    "session_already_active": "Talabgor boshqa kompyuterda imtihonda",
    "machine_not_verified": "Kompyuter tasdiqlanmadi",
}


class CandidatePage(QWidget):
    """Talabgorni JSHSHIR bo'yicha topish."""

    candidate_ready = pyqtSignal(object)  # Candidate
    #: Talabgor topildi (karta ko'rsatildi), «Davom etish» hali bosilmagan.
    #: `MainWindow` shu paytda yuz kamerasini oldindan ochadi
    #: (`FaceIDPage.prewarm_camera`).
    candidate_found = pyqtSignal()
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
        #: Oxirgi xato tarmoq sababli bo'ldimi — aloqa tiklanganda
        #: operatorga "endi qaytadan tekshirish mumkin" deyish uchun.
        self._network_failed = False
        #: Kamera tekshiruvi haqidagi ogohlantirish ekranda turibdimi -
        #: taymer uni har 30 s da qayta chizmasligi va boshqa xabarni
        #: (masalan bron xatosini) bosib ketmasligi uchun.
        self._check_warned = False
        #: Natija kartasi ko'rsatayotgan JSHSHIR ("" — karta yo'q). Shu
        #: raqam maydonda turguncha «TEKSHIRISH» o'chiq: qayta bosish
        #: platformaga takroriy so'rov yuborib JSHSHIR throttle
        #: byudjetini sarflardi va ekrandagi natijani hech narsa
        #: o'zgartirmasdan qaytadan chizardi.
        self._found_pinfl = ""
        #: Ochiq oferta dialogi (`None` — yopiq).
        self._offer_dialog = None
        self._setup_ui()
        network_status().changed.connect(self._on_network_changed)
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(_CHECK_POLL_MS)
        self._check_timer.timeout.connect(self._on_check_tick)
        self._check_timer.start()

    # ------------------------------------------------------------------
    # Ko'rinish
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 24, 48, 24)
        root.setSpacing(14)

        # Bosqich nomi bilan (`FlowStepper`), "2 / 4" raqami emas: ekran
        # oldida talabgor turadi va u butun yo'lni ko'rishi kerak.
        self.header = PageHeader(
            "Talabgorni JSHSHIR bo'yicha tekshirish",
            step=2,
            show_back=False,
            show_logout=False,
            chips=("region", "zone", "ip"),
            stepper=True,
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
        # Chetlar - kartalar soyasi (`md3.elevate`) uchun joy.
        self._column.setContentsMargins(6, 0, 6, 8)
        self._column.setSpacing(14)
        self._column.addWidget(self._build_search_card())
        self._column.addWidget(self._build_result_card())

        center.addWidget(column)
        center.addStretch(1)
        root.addLayout(center)

        root.addStretch(3)

        self.result_card.setVisible(False)
        self.overlay = BusyOverlay(self)

    def _build_search_card(self) -> Card:
        card = Card()
        card.body.setContentsMargins(28, 24, 28, 24)
        card.body.setSpacing(12)
        elevate(card)

        # MD3 sarlavha: tonal belgi + sarlavha + izoh. Matn TALABGORGA
        # ham tushunarli: "identifikator" emas, hujjatdagi raqam.
        # Topilgan talabgor ko'rinib turganda bu qism YIG'ILADI
        # (`_update_pinfl_state`): 1366x768 da natija kartasi bilan sig'ishi
        # uchun. Maydonning o'zi va hisoblagich qoladi.
        self._intro = QWidget()
        # Global `QWidget { background }` qoidasi oq karta ichida sahifa
        # fonini chizib qo'yardi.
        self._intro.setStyleSheet("background: transparent;")
        top = QHBoxLayout(self._intro)
        top.setContentsMargins(0, 0, 0, 4)
        top.setSpacing(14)
        top.addWidget(IconBadge("id", 48), 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("JSHSHIR raqami")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: {};".format(COLORS["on_surface"])
        )
        titles.addWidget(title)
        caption = QLabel("Pasport yoki ID-kartadagi 14 xonali shaxsiy raqamni kiriting")
        caption.setWordWrap(True)
        caption.setStyleSheet(
            "font-size: 13px; color: {};".format(COLORS["on_surface_variant"])
        )
        titles.addWidget(caption)
        top.addLayout(titles, 1)
        card.body.addWidget(self._intro)

        self.pinfl_input = QLineEdit()
        self.pinfl_input.setPlaceholderText("_ _ _ _ _ _ _ _ _ _ _ _ _ _")
        self.pinfl_input.setMaxLength(PINFL_LENGTH)
        self.pinfl_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Tozalash tugmasi maydonning ICHIDA: xato kiritilgan raqamni
        # 14 marta Backspace bosib o'chirish operatorning har
        # talabgorda takrorlanadigan ishi bo'lardi.
        self.pinfl_input.setClearButtonEnabled(True)
        self.pinfl_input.setStyleSheet(code_field_style(66))
        self.pinfl_input.textChanged.connect(self._on_pinfl_changed)
        self.pinfl_input.returnPressed.connect(self._on_lookup)
        card.body.addWidget(self.pinfl_input)

        # Nechta raqam qolgani BIR QARASHDA (hisoblagich o'qishni talab
        # qiladi): 14 segment, to'lganda bir lahza yorishadi.
        self.progress = SegmentProgress(PINFL_LENGTH)
        card.body.addWidget(self.progress)

        helper = QHBoxLayout()
        helper.setContentsMargins(2, 0, 2, 0)
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

        card.body.addSpacing(2)
        self.lookup_btn = RippleButton("TEKSHIRISH")
        self.lookup_btn.setStyleSheet(primary_button_style(52))
        self.lookup_btn.setEnabled(False)
        self.lookup_btn.clicked.connect(self._on_lookup)
        card.body.addWidget(self.lookup_btn)

        # BARCHA javob bitta joyda — tugmaning OSTIDA va bitta MD3
        # komponentida (`notice.Notice`): oddiy xabar ham, bron bo'yicha
        # rad javobi ham. Ilgari bron javobi alohida oq kartada, qolganlari
        # karta ichidagi markazlashgan qatorda chiqardi - operator bir xil
        # savolga ("nega o'tmadi?") ikki xil joyga qarardi. Ikkalasi hech
        # qachon birga ko'rinmaydi.
        #
        # IXCHAM shakl (`compact=True`): to'liq bloklar qidiruv kartasini
        # ikki baravar cho'zib, 768 px ekranda natija kartasini pastga
        # surardi; server matni tooltip'ga o'tadi.
        self.message = Notice(compact=True)
        card.body.addWidget(self.message)
        self.seat_notice = SeatNotice(compact=True)
        card.body.addWidget(self.seat_notice)

        self._update_pinfl_state("")
        return card

    def _build_result_card(self) -> Card:
        self.result_card = Card()
        self.result_card.body.setContentsMargins(24, 20, 24, 22)
        self.result_card.body.setSpacing(12)
        elevate(self.result_card, 2)

        # Holat qatori: "topildi" ATAYLAB matn bilan ham (faqat yashil
        # rang emas) - talabgor ham, operator ham bir qarashda o'qiydi.
        status = QHBoxLayout()
        status.setSpacing(8)
        status.addWidget(StatusIcon("ready", 22), 0, Qt.AlignmentFlag.AlignVCenter)
        found = QLabel("Talabgor topildi")
        found.setStyleSheet(
            "font-size: 13px; font-weight: 700; letter-spacing: 0.3px; color: {};".format(
                COLORS["primary_dark"]
            )
        )
        status.addWidget(found, 0, Qt.AlignmentFlag.AlignVCenter)
        status.addStretch(1)
        # Oferta holati — qisqa matn: qator 1366x768 da hujjat nishoni
        # ("Hujjat rasmi yo'q — operator tasdiqlaydi") bilan sig'ishi kerak.
        self.offer_badge = QLabel("")
        self.offer_badge.setFixedHeight(26)
        self.offer_badge.setVisible(False)
        status.addWidget(self.offer_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.reference_badge = QLabel("")
        self.reference_badge.setFixedHeight(26)
        status.addWidget(self.reference_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.result_card.body.addLayout(status)

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
            "font-size: 22px; font-weight: 700; color: {};".format(COLORS["text"])
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

        info.addSpacing(8)
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
        # Joy va vaqt — rasm yonidagi ustunda, alohida qatorda EMAS:
        # 1366x768 ekranda natija kartasi qidiruv kartasi bilan birga
        # sig'ishi kerak (ilgari 884 px bo'lib, «Yuzni tekshirish»
        # ekrandan chiqib ketardi).
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        tiles.addWidget(self._build_seat_panel(), 1)
        tiles.addWidget(self._build_duration_panel(), 1)
        info.addLayout(tiles)
        info.addStretch(1)

        row.addLayout(info, 1)
        self.result_card.body.addLayout(row)

        self.result_card.body.addSpacing(4)
        self.next_btn = RippleButton("YUZNI TEKSHIRISH")
        self.next_btn.setStyleSheet(primary_button_style(52))
        self.next_btn.clicked.connect(self._on_next)
        self.result_card.body.addWidget(self.next_btn)
        return self.result_card

    @staticmethod
    def _tile(object_name: str, caption_text: str) -> tuple:
        """
        Tonal katak: tepada kichik yorliq, ostida yirik qiymat.

        Yorliq va qiymat USTMA-UST (yonma-yon emas): rasm yonidagi tor
        ustunda ikkita katak sig'ishi kerak.
        """
        panel = QFrame()
        panel.setObjectName(object_name)
        panel.setStyleSheet(surface_container_style(object_name, tone="high"))
        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 8, 14, 9)
        box.setSpacing(0)
        caption = QLabel(caption_text)
        caption.setWordWrap(True)
        caption.setStyleSheet(
            "font-size: 10px; font-weight: 700; letter-spacing: 0.6px; "
            "background: transparent; color: {};".format(COLORS["primary_dark"])
        )
        box.addWidget(caption)
        value = QLabel("-")
        value.setStyleSheet(
            "font-size: 20px; font-weight: 700; background: transparent; "
            "color: {};".format(COLORS["primary_deep"])
        )
        box.addWidget(value)
        return panel, caption, value

    def _build_duration_panel(self) -> QFrame:
        """
        Test vaqti - IDENTIFIKATORLAR QATORIDA EMAS, alohida katakda.

        Sabab auditoriyada: raqamlar qatorini operator o'qiydi, test
        vaqtini esa TALABGOR so'raydi va u ekranga uzoqdan qaraydi.
        Kichik katakda, "Abituriyent ID" yonida turgan "3 soat"
        yozuvi shu savolga javob bermasdi - u boshqa ma'lumot
        turkumiga tegishli.
        """
        panel, _caption, self.duration_value = self._tile(
            "durationPanel", "TESTGA AJRATILGAN VAQT"
        )
        self.duration_panel = panel
        panel.setVisible(False)
        return panel

    def _build_seat_panel(self) -> QFrame:
        """
        Bron bo'yicha joy TASDIQLANDI — vaqt katagi bilan yonma-yon.

        Faqat bron yuritiladigan sessiyada ko'rinadi. U "to'g'ri stoldami?"
        degan savolga ijobiy javob va raqam: operator talabgorga "siz
        №12 dasiz" deb aytadi.
        """
        panel, self.seat_caption, self.seat_value = self._tile("seatPanel", "JOY TASDIQLANDI")
        self.seat_panel = panel
        panel.setVisible(False)
        return panel

    def _apply_seat(self, candidate: Candidate) -> None:
        seat = candidate.seat or {}
        number = seat.get("number")
        self.seat_value.setText("№{}".format(number) if number else seat.get("inventory_code", ""))
        # Erkin joylashuv: stol yaroqli, lekin hali BAND EMAS - server uni
        # test boshlanganda yozadi. "Tasdiqlandi" deyish operatorni joy
        # allaqachon olingan deb o'ylatardi.
        auto = bool(seat.get("auto_assign"))
        self.seat_caption.setText("TEST BOSHLANGANDA BIRIKTIRILADI" if auto else "JOY TASDIQLANDI")
        where = " · ".join(part for part in (
            seat.get("label"), seat.get("zone_name"), seat.get("region_name")
        ) if part)
        self.seat_panel.setToolTip(
            "{}\nErkin joylashuv: talabgor test boshlanganda shu kompyuterga "
            "biriktiriladi".format(where) if auto else where
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
        staff = self._state.staff
        device = self._state.device

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

        if self._offer_dialog is not None:
            # Sahifa yangi talabgor uchun tozalanmoqda — eski talabgorning
            # ofertasi ekranda qolmasin.
            self._offer_dialog.reject()
        self._found_pinfl = ""
        self.pinfl_input.clear()
        self.message.clear_message()
        self._check_warned = False
        self.result_card.setVisible(False)
        self.seat_notice.hide()
        self.pinfl_input.setFocus()
        self._warn_camera_check()

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
        # Kamera ogohlantirishi BIRGA ko'rsatiladi, bosib ketilmaydi:
        # ikkalasi ham "keyingi talabgordan oldin nima qilish kerak"
        # degan savolga javob va operator ikkalasini ham o'qishi kerak.
        problem = self._camera_check_problem()
        if result.get("error"):
            self._show_with_check(
                "Yakun serverga yetmadi",
                "Keyingi talabgor kira olmasa, administratorga murojaat qiling.",
                "warning",
                problem,
            )
            return
        if result.get("seat_released"):
            label = (result.get("seat") or {}).get("label") or "Kompyuter"
            text = "«{}» bo‘shatildi".format(label)
            if problem:
                self._show_with_check("Imtihon yakunlandi", text + ".", "warning", problem)
            else:
                self.message.show_message(
                    text + " — keyingi talabgorni kiritishingiz mumkin.",
                    "success",
                    title="Imtihon yakunlandi",
                )

    def _show_with_check(self, title: str, text: str, kind: str, problem: str) -> None:
        self.message.show_message(
            "{}\n{}".format(text, problem) if problem else text,
            "warning" if problem else kind,
            title=title,
        )
        self._check_warned = bool(problem)

    # ------------------------------------------------------------------
    # Kamera tekshiruvi muddati
    # ------------------------------------------------------------------
    def _camera_check_problem(self) -> str:
        """
        Kamera tekshiruvi muddati tugagan/tugayapti - operatorga matn.

        Server natijani OXIRGI tekshiruvdan 4 soat saqlaydi va uni
        faqat `proctoring/start/` da talab qiladi - FaceID va shaxs
        tasdig'idan KEYIN. Bu sahifa oqimdagi eng arzon to'xtash
        nuqtasi: talabgor hali hech narsadan o'tmagan va platformaga
        so'rov ketmagan.

        Bo'sh satr - muammo yo'q YOKI noma'lum (eski server muddat
        bermaydi, siyosat tekshiruvni talab qilmaydi). Noma'lumni
        to'smaymiz: yakuniy qaror baribir serverniki.
        """
        if not camera_check_required(self._state.config):
            return ""
        left = self._state.camera_check_left()
        if left is None or left > _CHECK_MARGIN_S:
            return ""
        # Yo'l parol bilan (Ctrl+Q): sahifada "Orqaga" tugmasi ataylab
        # yo'q (modul docstring'i), ekran oldida talabgor turadi.
        how = "Ctrl+Q → «Imtihon tanlashga qaytish»."
        if left <= 0:
            return "Kamera tekshiruvi muddati tugagan — test ochilmaydi. " + how
        return "Kamera tekshiruvi muddati {} daqiqadan keyin tugaydi. ".format(
            max(1, round(left / 60))) + how

    def _warn_camera_check(self) -> bool:
        """Ogohlantirishni ko'rsatadi. `True` - muammo bor."""
        problem = self._camera_check_problem()
        if problem:
            self.message.show_message(problem, "warning", title="Kamerani qayta tekshiring")
        self._check_warned = bool(problem)
        return bool(problem)

    def _on_check_tick(self) -> None:
        # Faqat kutish holatida: natija kartasi ochiq bo'lsa operator
        # allaqachon talabgor bilan ishlayapti, so'rov ketayotganda esa
        # xabar qatori so'rov natijasiga tegishli.
        if (
            self._check_warned
            or not self.isVisible()
            or self.result_card.isVisible()
            or self.seat_notice.isVisible()
            or self.overlay.isVisible()
        ):
            return
        self._warn_camera_check()

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
        # Raqam o'zgardi — ekrandagi natija ENDI BOSHQA odamniki: karta
        # yashiriladi, aks holda operator yangi JSHSHIR yonida eski
        # talabgorni ko'rib «Yuzni tekshirish» ni bosib yuborardi.
        if self._found_pinfl and digits != self._found_pinfl:
            self._found_pinfl = ""
            self.result_card.setVisible(False)
        left = PINFL_LENGTH - len(digits)
        complete = left <= 0
        self.progress.set_value(len(digits))
        self.counter_label.setText("{} / {}".format(len(digits), PINFL_LENGTH))
        self.counter_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: {};".format(
                COLORS["primary_dark"] if complete else COLORS["text_muted"]
            )
        )
        if self._found_pinfl:
            self.hint_label.setText("Talabgor topildi — boshqasi uchun raqamni o'zgartiring")
        elif complete:
            self.hint_label.setText("Tayyor — Enter bosing")
        elif digits:
            self.hint_label.setText("Yana {} ta raqam".format(left))
        else:
            self.hint_label.setText("Enter tugmasi bilan ham qidirish mumkin")
        self.lookup_btn.setEnabled(complete and not self._found_pinfl)
        # Topilgan talabgor ko'rinib turganda «TEKSHIRISH» YASHIRIN: u
        # baribir o'chiq, joyi esa 1366x768 da natija kartasiga kerak.
        # Raqam o'zgarsa karta yopiladi va tugma qaytadi.
        self.lookup_btn.setVisible(not self._found_pinfl)
        self._intro.setVisible(not self._found_pinfl)

    def _on_lookup(self) -> None:
        pinfl = self.pinfl_input.text().strip()
        exam = self._state.selected_exam
        if self._found_pinfl and pinfl == self._found_pinfl:
            # Enter ham tugma bilan bir qoidada (tugma o'chiq).
            return
        if len(pinfl) != PINFL_LENGTH:
            self.message.show_message("JSHSHIR 14 xonali bo'lishi kerak", "warning")
            return
        if exam is None:
            self.message.show_message("Avval imtihonni tanlang", "warning")
            return
        if self._warn_camera_check():
            # Qidiruv YUBORILMAYDI: u platformaga boradi va JSHSHIR
            # throttle byudjetini sarflaydi, imtihon esa baribir
            # ochilmasdi.
            return

        self._state.reset_flow()
        self.result_card.setVisible(False)
        self.seat_notice.hide()
        self.message.clear_message()
        self._check_warned = False
        self.overlay.start("Test platformasidan so'ralmoqda...")
        self.lookup_btn.setEnabled(False)

        worker = ApiWorker(
            self._repo.lookup_candidate,
            pinfl=pinfl,
            exam_id=exam.id,
            # Kompyuter broni shu mashina bilan solishtiriladi (asos -
            # Machine UUID, handshake yuborgan qiymatning o'zi).
            machine_uuid=self._state.machine.get("machine_uuid", ""),
            mac_address=self._state.machine.get("mac", ""),
            parent=self,
        )
        worker.succeeded.connect(self._on_found)
        worker.failed_details.connect(self._on_failed)
        self._workers.run(worker)

    def _on_found(self, payload) -> None:
        self._network_failed = False
        self.overlay.stop()

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

        self._apply_offer(candidate)

        self._found_pinfl = self._state.pinfl
        self._update_pinfl_state(self._found_pinfl)
        # Karta "ochiladi" (MD3 motion): yangi ma'lumot qayerda paydo
        # bo'lganini ko'z kuzatadi.
        reveal(self.result_card)
        # "Talabgor topildi" degan xabar ATAYLAB yo'q: natija
        # kartasining o'zi paydo bo'lishi ayni shu narsani aytadi
        # va uni matn bilan takrorlash ekranga ma'lumot qo'shmasdan
        # joy egallardi. Xabar qatori faqat XATO va OGOHLANTIRISH
        # uchun qoladi - ular ko'rinadigan natija bermaydi.
        self.message.clear_message()
        # Fokus KEYINGI qadamga o'tadi: operator natijani o'qib,
        # Enter bilan davom eta oladi va sichqonchaga qo'l uzatmaydi.
        self.next_btn.setFocus()
        self.candidate_found.emit()

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
        #
        # Sarlavha — "nima bo'ldi" (bizniki, qisqa), matn — server yoki
        # platformaning O'Z so'zi (o'zgartirilmaydi). Sarlavhasi yo'q kod
        # (kutilmagan xato) faqat matn bilan chiqadi.
        if code == "candidate_not_found":
            self.message.show_message(message, "warning", title="Talabgor topilmadi")
            # Maydon silkinadi - tuzatish SHU YERDA (raqamni tekshirish).
            shake(self.pinfl_input)
            return
        if code == "candidate_not_eligible":
            self.message.show_message(message, "warning", title="Platforma ruxsat bermadi")
            return
        # Tarmoq/server vaqtincha — JSHSHIR to'g'ri, faqat qayta urinish
        # kerak. Aloqa tiklanganda `_on_network_changed` aytadi.
        self._network_failed = code in ("network", "server_unavailable")
        # Chegara xatosi emas — "kuting" yoki "boshqasini qidiring";
        # sarlavha NIMA to'silganini aytadi (`details.scope`).
        scope = throttle_scope(details) if code == "throttled" else ""
        if scope:
            self.message.show_message(message, "warning", title=THROTTLE_SCOPES[scope][0])
            return
        self.message.show_message(message, "error", title=_ERROR_TITLES.get(code, ""))

    def _on_network_changed(self, online: bool) -> None:
        """Aloqa tiklandi — oldingi tarmoq xatosi o'rniga ko'rsatma."""
        if not online or not self._network_failed or not self.isVisible():
            return
        self._network_failed = False
        self.message.show_message(
            "«TEKSHIRISH» ni qayta bosing.", "info", title="Server bilan aloqa tiklandi"
        )

    def _on_next(self) -> None:
        candidate = self._state.candidate
        if candidate is None:
            return
        # Rozilik YUZ TEKSHIRUVIDAN OLDIN: FaceID biometrik ma'lumotni
        # serverga yuboradi. Rozilik serverga yuborilmaydi — «Roziman»
        # siz bu qadamdan o'tib bo'lmaydi, xolos.
        if candidate.offer is not None and not candidate.offer.accepted:
            self._open_offer(candidate)
            return
        self.candidate_ready.emit(candidate)

    # ------------------------------------------------------------------
    # Oferta
    # ------------------------------------------------------------------
    def _apply_offer(self, candidate: Candidate) -> None:
        """
        Nishon va asosiy tugma — keyingi qadam nima ekanini aytadi.

        Tugma nomi HARAKATNING O'ZI: rozilik kerak bo'lsa u ofertani
        ochadi, ya'ni "YUZNI TEKSHIRISH" deyish operatorni chalg'itardi.
        Rozilikdan keyin yuz tekshiruvi qo'shimcha bosishsiz ochiladi.
        """
        offer = candidate.offer
        pending = offer is not None and not offer.accepted
        self.next_btn.setText("OFERTA BILAN TANISHISH" if pending else "YUZNI TEKSHIRISH")
        self.next_btn.setToolTip(
            "Talabgor oferta bilan tanishib rozilik bergach, yuz tekshiruvi ochiladi"
            if pending else ""
        )
        if offer is None:
            self.offer_badge.setVisible(False)
            return
        self.offer_badge.setText("Rozilik berildi" if offer.accepted else "Rozilik kerak")
        self.offer_badge.setStyleSheet(badge_style("success" if offer.accepted else "info"))
        self.offer_badge.setToolTip(
            "Talabgor «{}» bilan tanishib, shaxsga doir ma'lumotlarini "
            "qayta ishlashga rozilik {}".format(
                offer.title or "Oferta", "berdi" if offer.accepted else "berishi kerak"
            )
        )
        self.offer_badge.setVisible(True)

    def _open_offer(self, candidate: Candidate) -> None:
        if self._offer_dialog is not None:
            return
        self.message.clear_message()
        dialog = OfferDialog(
            self.window(),
            offer=candidate.offer,
            candidate_name=candidate.display_name,
            masked_pinfl=candidate.masked_pinfl,
        )
        dialog.finished.connect(self._on_offer_closed)
        self._offer_dialog = dialog
        # `open()` — `exec()` emas: ichki hodisa sikli kerak emas, natija
        # `finished` signalida keladi.
        dialog.open()

    def _on_offer_closed(self, result: int) -> None:
        dialog, self._offer_dialog = self._offer_dialog, None
        if dialog is not None:
            dialog.deleteLater()
        candidate = self._state.candidate
        if candidate is None or candidate.offer is None:
            return
        if result == QDialog.DialogCode.Accepted:
            # Faqat shu qidiruv uchun: keyingi JSHSHIR qidiruvi yangi
            # `Candidate` beradi va oferta yana so'raladi.
            candidate.offer.accepted = True
            self._apply_offer(candidate)
            self.candidate_ready.emit(candidate)
            return
        # Rad etildi: talabgor shu sahifada qoladi, qaror qaytariladigan —
        # fikrini o'zgartirsa tugma ofertani qayta ochadi.
        self.message.show_message(
            "Rozilik berilmaguncha yuz tekshiruvi va imtihon boshlanmaydi. "
            "Talabgor fikrini o'zgartirsa, tugmani qayta bosing.",
            "warning",
            title="Talabgor ofertaga rozilik bermadi",
        )
        self.next_btn.setFocus()

    def shutdown(self) -> None:
        self._workers.wait_all()
