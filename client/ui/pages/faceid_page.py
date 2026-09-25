"""
4-SAHIFA - FaceID tekshiruvi.

Oqim:
  1. Kamera ochiladi (alohida thread).
  2. Pasport rasmidan etalon embedding olinadi (bu ham fon thread'ida -
     InsightFace chaqiruvi ~200 ms, UI thread'da qilinsa oyna sakraydi).
  3. Har kadr uchun ball hisoblanadi (`FaceEngine.compare`).
  4. Ketma-ket `face.match_streak` kadr chegaradan yuqori bo'lsa -
     tasdiqlangan. Bitta kadr yetarli emas: bitta muvaffaqiyatli rakurs
     tasodif bo'lishi mumkin, ketma-ketlik esa yo'q.
  5. Backendga `face/verify/` yuboriladi -> sessiya ochiladi.
  6. Darhol `exam/access/` sinaladi. `identity_not_confirmed` qaytsa -
     operator ekranda hujjat rasmini jonli kadr bilan solishtirib
     "Davom etish" ni bosadi. Hujjat turi va raqami SO'RALMAYDI:
     operator ularni baribir hujjatdan ko'chirardi va tekshiruvga
     hech nima qo'shmasdi - javobgarlik esa tasdiqlagan xodimning
     ismi bilan qayd etiladi.

     BU QADAMDA RAD ETISH TUGMASI YO'Q. Hujjat mos kelmasa operator
     "Qaytadan urinish" ga qaytadi (yangi talabgor) yoki proktor
     sessiyani paneldan to’xtatadi - qaror u yerda ko'proq
     ma'lumot bilan qabul qilinadi.

SOLISHTIRISH BUTUNLAY SHU YERDA. Ikkala embedding ham clientda:
etalon pasport rasmidan, jonli vektor kameradan. Serverga natija
ketadi - ball va o'sha paytdagi KADR.

CHEGARA SERVERDAN. `AppState.config` dagi imtihon profilidan
(`face.min_score_initial`), zaxira - `FACE_MATCH_THRESHOLD`. Oqim
qoidalari (sanoq, `face.match_streak`, `face.fail_streak`,
`face.fail_min_seconds`) ham o'sha profildan - `services/runtime_settings`,
zaxira `.env`. Client va server bir xil shkalani ishlatadi
(`face_engine.similarity_score` == `common/utils/vectors.py`), aks
holda bitta chegara ikki joyda ikki xil ma'noni anglatardi.

IKKI XIL YAKUN, IKKALASI HAM SERVERGA BORADI:

    mos keldi   -> `face/verify/`  : sessiya ochiladi, rasm+ball saqlanadi
    mos kelmadi -> `face/attempt/` : sessiya YO'Q, rasm+ball saqlanadi

Ikkinchisi `face.fail_streak` ta ketma-ket muvaffaqiyatsiz kadrdan
keyin BIR MARTA yuboriladi va `challenge` ni sarflamaydi - operator
"Qaytadan urinish" ni bosib yangi urinish boshlaydi. Aynan shu yozuv
"kim kira olmadi?" degan savolga javob beradi.

Etalon rasm bo'lmasa (tashqi platforma bermagan), solishtirish o'rniga
ENROLLMENT rejimi ishlaydi: yuz sifatli aniqlangani yetarli, qaror esa
operatorning hujjat tekshiruviga qoladi. Bu backend mantig'i bilan bir
xil - `has_reference_face=False` holati.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from typing import Optional

import numpy as np
from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import FACE_MATCH_THRESHOLD
from services import runtime_settings
from services.app_state import AppState, ProctoringSession
from services.camera_worker import (
    CameraWorker,
    encode_jpeg,
    retire_camera,
    source_for_role,
)
from services.face_engine import FaceEngine, similarity_score
from services.repositories import ProctoringRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import COLORS, badge_style, primary_button_style
from ui.widgets.camera_view import CameraView, PhotoView
from ui.widgets.header import PageHeader, ip_chip_hints
from ui.widgets.indicators import BusyOverlay, Card, MessageBar

log = logging.getLogger(__name__)

#: O'ng ustunning qat'iy kengligi.
#:
#: Cho'ziluvchan ustunda hujjat tasdig'i kartasi ochilganda kenglik
#: o'zgarib, butun ekran qayta joylashardi. Bu qiymat ichida rasm
#: (160) + info yonma-yon bemalol turadi.
_SIDE_WIDTH = 420

#: Hujjat rasmi - BU SAHIFADA KATTA (nisbat 3:4).
#:
#: Operator uni jonli kadr bilan solishtiradi; qidiruv sahifasida
#: esa rasm kichik, chunki u yerda vazifa boshqa.
_PHOTO_WIDTH = 264
_PHOTO_HEIGHT = 352

#: Rasm shundan kichik bo'lmaydi.
#:
#: Pastki chegara KERAK: hujjat rasmi bu sahifada dalil, va uni
#: "sig'sin" deb pochta markasiga aylantirish operatorni faqat
#: foizga tayanishga majbur qilardi. 160 px - talabgorni qidirish
#: sahifasidagi rasm bilan bir xil o'lcham, ya'ni "to'g'ri odammi?"
#: degan qarash uchun yetarli deb qabul qilingan chegara.
#:
#: 1366x768 ekranda shaxs tasdig'i kartasi ochilganda yon ustunga
#: aynan shuncha joy qoladi - chegarani balandroq qo'yish o'sha
#: holatda yorliqlarni rasm ustiga chiqarardi.
_PHOTO_MIN_HEIGHT = 160



#: ENROLLMENT REJIMI - HOZIRCHA O'CHIRILGAN.
#:
#: U shunday ishlaydi: tashqi platforma hujjat rasmini bermasa,
#: solishtirish o'rniga sifatli kadr yetarli deb hisoblanadi va
#: shaxs uchun javobgarlik butunlay operatorning hujjat
#: tekshiruviga o'tadi (`has_reference_face=False`).
#:
#: NIMA UCHUN O'CHIRILDI: hozirgi o'rnatishda platforma rasmni har
#: doim beradi, ya'ni "rasm yo'q" holati amalda faqat NOSOZLIK
#: belgisidir (platforma javobi buzilgan, rasm bo'sh keldi). Bunday
#: holatda talabgorni jimgina kiritib yuborish tekshiruvni o'zini
#: bekor qiladi - operator esa hech qanday farqni sezmaydi.
#:
#: Kod OLIB TASHLANMADI: rasmsiz platforma bilan integratsiya
#: kelajakda paydo bo'lishi mumkin va o'shanda bu bayroq `True`
#: qilinadi. Server tomoni ham joyida turibdi
#: (`verify_initial_face` ballsiz so'rovni qabul qiladi).
_ENROLLMENT_ENABLED = False

#: Ball chegaradan shuncha past bo'lsa - "umuman boshqa odam".
#:
#: ArcFace shkalasida (`similarity_score`) bir xil odamning
#: kadrlari 70-85, butunlay boshqa odam esa ~50 beradi. Ya'ni
#: chegaradan 12 ball past tushish "sifat yomon" emas, "bu boshqa
#: odam" degani va operator BOSHQA ish qilishi kerak: yorug'likni
#: emas, JSHSHIR va talabgorning o'zini tekshirishi kerak.
_FAR_MISS_GAP = 12


def _fallback_threshold() -> int:
    """
    Sozlama kelmagan holatdagi chegara (0..100).

    Imtihon profili SERVERDAN keladi va odatda mavjud
    (`AppState.config`). Lekin u o'tkinchi tarmoq xatosi tufayli
    bo'sh qolishi mumkin - o'shanda tekshiruvni butunlay o'chirish
    ham, hammani o'tkazib yuborish ham noto'g'ri bo'lardi.
    """
    return similarity_score(FACE_MATCH_THRESHOLD)

class FaceIDPage(QWidget):
    """Yuzni real vaqtda solishtirish va sessiyani ochish."""

    #: Imtihonga kirish ma'lumoti tayyor (`exam/access/` javobi).
    access_granted = pyqtSignal(object)
    back_requested = pyqtSignal()
    logout_requested = pyqtSignal()
    #: Kuzatuv kamera tekshiruvi tufayli rad etildi - operator imtihon
    #: tanlash sahifasida kamerani tekshiradi, SESSIYA SAQLANADI.
    camera_check_requested = pyqtSignal()

    def __init__(self, state: AppState, repo: ProctoringRepository, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        self._workers = WorkerHolder()
        self._camera: Optional[CameraWorker] = None
        self._engine = FaceEngine()

        self._reference: Optional[np.ndarray] = None
        self._reference_ready = False
        self._streak = 0
        #: Ketma-ket MOS KELMAGAN kadrlar - urinishni yopish uchun.
        self._fail_streak = 0
        #: Mos kelmaslik QACHON boshlangani (`time.monotonic`).
        #: `0.0` - hozir mos kelmaslik seriyasi yo'q.
        self._fail_since = 0.0
        self._best_score = 0
        #: SESSIYANI OCHGAN ball - serverga yuborilgani.
        #
        # `_best_score` dan FARQ QILADI va ikkalasi ham kerak.
        # Tasdiqlangandan keyin ekranda AYNAN shu ko'rsatiladi:
        # `FaceVerificationLog` ga ham, panelga ham shu tushadi va
        # ekranda boshqa son turishi bitta hodisa uchun ikkita
        # raqam degani bo'lardi ("nega panelda 66%, ekranda 71%?").
        # Eng yuqori ball esa MUVAFFAQIYATSIZ urinishda ma'noga ega:
        # u yerda savol "eng yaxshi holatda qancha chiqdi?".
        self._verified_score: Optional[int] = None
        self._verifying = False
        self._verified = False
        #: Urinish muvaffaqiyatsiz yakunlandi (rasm serverga ketdi).
        self._failed = False
        self._last_embedding: Optional[np.ndarray] = None
        #: Oxirgi kadr - serverga yuboriladigan JONLI RASM.
        #
        # Nusxa OLINMAYDI: `CameraWorker` allaqachon `frame.copy()`
        # emit qiladi va bu yerda faqat havola saqlanadi. Kadr
        # signal navbatida rasmdan OLDIN keladi, ya'ni `_on_face`
        # chaqirilganda bu aynan tahlil qilingan kadr.
        self._last_frame = None
        #: Imtihon profilidagi chegara (0..100). `start()` da o'qiladi.
        self._threshold = _fallback_threshold()
        #: Kirish tekshiruvi OQIMI - imtihon profilidan (`config.face`),
        #: `start()` da chegara bilan BIRGA o'qiladi. Ilgari ular
        #: modul darajasida `.env` dan olinardi va panelda o'zgartirib
        #: bo'lmasdi; boshlang'ich qiymat - `.env` zaxirasi.
        self._guide_seconds = runtime_settings.fallback("face.guide_seconds")
        self._match_streak = runtime_settings.fallback("face.match_streak")
        self._fail_streak_limit = runtime_settings.fallback("face.fail_streak")
        self._fail_min_seconds = runtime_settings.fallback("face.fail_min_seconds")
        #: `face/verify/` javobini kutayotgan etalon.
        self._pending_reference: Optional[np.ndarray] = None
        #: Test vaqti chipining matni ("3 soat"). Bo'sh bo'lsa chip
        #: umuman ko'rsatilmaydi - joy bo'shaganda ham (`_apply_compact`).
        self._duration_text = ""
        #: Yuzni joylashtirish bosqichi:
        #:   "waiting"   - kamera ochilmoqda, birinchi kadr kutilmoqda;
        #:   "countdown" - oval ko'rsatilgan, sanoq ketyapti;
        #:   "done"      - aniqlash va solishtirish ishlayapti.
        #:
        #: Sanoq BIRINCHI KADR kelganda boshlanadi, kamera ishga
        #: tushirilganda emas: Windows'da qurilma 2-4 soniyada
        #: ochiladi va sanoqning yarmi bo'sh ekranda o'tib ketardi -
        #: talabgor o'zini ko'rmasdan yuzini to'g'irlay olmaydi.
        self._guide_state = "done"
        self._guide_timer = QTimer(self)
        self._guide_timer.setSingleShot(True)
        self._guide_timer.timeout.connect(self._finish_guide)

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 36)
        root.setSpacing(22)

        # Sarlavhada TEST nomi turadi (talabgor sahifasidagi bilan bir
        # xil qoida): operator kim ekanini o'zi biladi, ekranda esa
        # doim ko'rinishi kerak bo'lgan narsa qaysi test ekani.
        #
        # "Orqaga" va "Chiqish" YO'Q: bu ekran oldida talabgor turadi
        # va sahifada faqat bitta yo'l bo'lishi kerak. Navigatsiya
        # yo'qolmaydi - Ctrl+Q dialogi "Talabgor ma'lumotlariga
        # qaytish" ni taklif qiladi (`MainWindow._back_action`) va u
        # parol bilan himoyalangan.
        self.header = PageHeader(
            "Yuzni tekshirish",
            "3-qadam · Talabgor kameraga qarasin",
            step=3,
            show_back=False,
            show_logout=False,
            chips=("region", "zone", "ip"),
        )
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(18)

        # --- Chap: kamera ---
        #
        # Kadr kartaning BUTUN balandligini egallaydi (`addWidget(…, 1)`).
        # Ilgari u o'z minimal o'lchamida turardi va ostida tushuntirib
        # bo'lmaydigan oq bo'shliq qolardi - karta esa baribir o'ng
        # ustun balandligiga cho'zilardi.
        camera_card = Card()
        self.camera_view = CameraView()
        camera_card.body.addWidget(self.camera_view, 1)

        status_row = QHBoxLayout()
        self.state_badge = QLabel("Kamera ishga tushmoqda")
        self.state_badge.setStyleSheet(badge_style("muted"))
        self.state_badge.setFixedHeight(24)
        # QAYSI KAMERA ochilgani — ekranda. Rollar tekshiruv
        # sahifasida tanlanadi va bu sahifada operator faqat
        # natijani ko'radi: nomi ko'rinmasa, "nega yuz topilmayapti?"
        # degan savolda kamera tanlovi eng oxirgi gumon bo'lardi.
        self.camera_label = QLabel("")
        self.camera_label.setProperty("role", "caption")
        self.score_label = QLabel("O'xshashlik: -")
        self.score_label.setProperty("role", "caption")
        status_row.addWidget(self.state_badge)
        status_row.addSpacing(10)
        status_row.addWidget(self.camera_label)
        status_row.addStretch()
        status_row.addWidget(self.score_label)
        camera_card.body.addLayout(status_row)
        body.addWidget(camera_card, 1)

        # --- O'ng: talabgor va tasdiq ---
        #
        # Ustun kengligi QAT'IY: cho'ziluvchan bo'lsa, hujjat tasdig'i
        # kartasi ochilganda butun ekran qayta joylashardi va operator
        # bosayotgan tugmasini yo'qotardi.
        side_panel = self._side_panel = QWidget()
        side_panel.setFixedWidth(_SIDE_WIDTH)
        side = QVBoxLayout(side_panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(16)

        # HUJJAT RASMI VA JONLI KADR — YONMA-YON VA TENG.
        #
        # Sahifaning butun vazifasi shu ikkisini solishtirish, ya'ni
        # ular bir xil "og'irlikda" bo'lishi kerak. Ilgari rasm
        # 150x190 edi va katta kadr yonida u ilova qilingan kichik
        # detalga o'xshardi - operator solishtirishni ko'z bilan
        # emas, faqat foizga tayanib bajarardi.
        candidate_card = Card("Talabgor")
        self.photo = PhotoView(width=_PHOTO_WIDTH, height=_PHOTO_HEIGHT)
        candidate_card.body.addWidget(self.photo, 0, Qt.AlignmentFlag.AlignHCenter)
        candidate_card.body.addSpacing(6)

        self.name_label = QLabel("-")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.name_label.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: {};".format(COLORS["text"])
        )
        candidate_card.body.addWidget(self.name_label)

        self.pinfl_label = QLabel("-")
        self.pinfl_label.setProperty("role", "caption")
        candidate_card.body.addWidget(self.pinfl_label)

        # TEST VAQTI SHU YERDA HAM. Talabgor ekran oldida turadi va
        # savolni aynan shu qadamda beradi ("qancha vaqtim bor?") -
        # javob uchun oldingi sahifaga qaytish kerak bo'lardi, u yerda
        # esa boshqa talabgorning ma'lumoti ochilardi.
        self.duration_badge = QLabel("")
        # O'RALMAYDI va balandligi QAT'IY (`mode_badge` bilan bir xil
        # sabab): chip bir qatorlik element.
        self.duration_badge.setFixedHeight(26)
        self.duration_badge.setStyleSheet(badge_style("info"))
        self.duration_badge.setVisible(False)
        candidate_card.body.addSpacing(8)
        candidate_card.body.addWidget(
            self.duration_badge, 0, Qt.AlignmentFlag.AlignLeft
        )

        self.mode_badge = QLabel("")
        # O'RALMAYDI: chip bir qatorlik element va `setWordWrap(True)`
        # uning sizeHint kengligini kichraytirib, matnni kesib
        # qo'yardi ("Hujjat rasmi bilan…").
        self.mode_badge.setFixedHeight(26)
        candidate_card.body.addSpacing(4)
        candidate_card.body.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignLeft)
        candidate_card.body.addStretch(1)
        # Cho'zilma koeffitsienti 1: karta o'ng ustunning qolgan
        # balandligini egallaydi va ikkala ustun BIR XIL balandlikda
        # tugaydi. Aks holda chapda baland karta, o'ngda esa kichik
        # karta va uning ostida tushuntirib bo'lmaydigan bo'shliq
        # qolardi.
        side.addWidget(candidate_card, 1)

        # Hujjat tasdig'i - faqat backend so'raganda ko'rinadi.
        #
        # HUJJAT TURI VA RAQAMI SO'RALMAYDI. Operator hujjatni
        # EKRANDA tekshiradi: chapda jonli kadr, o'ngda platformadan
        # kelgan hujjat rasmi - haqiqiy solishtirish o'sha yerda
        # bo'ladi. Raqamni qo'lda kiritish har talabgorda
        # takrorlanadigan ish edi va u tekshiruvga hech nima
        # qo'shmasdi: operator uni baribir hujjatdan ko'chirardi,
        # xato ko'chirilgan raqam esa audit izini yolg'on qilardi.
        #
        # Javobgarlik saqlanadi: tasdiqlagan xodimning ismi va vaqti
        # `identity` meta'siga yoziladi (`confirm_identity`).
        # KARTADA FAQAT AMAL QOLADI: sarlavha ham, tushuntirish
        # matni ham yo'q.
        #
        # Ikkalasi ham ekranda ALLAQACHON javob berilgan savolni
        # takrorlardi: chap ustunda jonli kadr, o'ng ustunda
        # hujjat rasmi yonma-yon turibdi va ularning ustida
        # xabar qatori ("Yuz tasdiqlandi...") nima qilish
        # kerakligini aytadi. Uchinchi marta yozish yon ustunni
        # past ekranda (1366x768) siqib, rasmni kichraytirardi —
        # aynan operator solishtirishi kerak bo'lgan rasmni.
        #
        # Karta qobig'i QOLADI: u `eventFilter` orqali kuzatiladi
        # va paydo bo'lganda rasm o'lchami qayta hisoblanadi
        # (`_fit_photo`). Ichki chetlari kichraytirilgan -
        # sarlavhali kartaning bo'shlig'i yolg'iz tugma atrofida
        # "karta bo'sh qolibdi" bo'lib ko'rinardi.
        self.identity_card = Card()
        self.identity_card.body.setContentsMargins(20, 16, 20, 16)
        self.identity_card.body.setSpacing(0)

        # YAGONA AMAL - to'ldirilgan tugma, to'liq kenglikda.
        #
        # "Rad etish" olib tashlandi: qaror bu ekranda bitta -
        # davom etish. Hujjat mos kelmasa operator "Qaytadan
        # urinish" ga qaytadi yoki proktor sessiyani paneldan
        # to'xtatadi (`sessions/{id}/terminate/`).
        #
        # Nomi "Tasdiqlash" emas, "Davom etish": tugma shaxsni
        # tasdiqlashdan tashqari keyingi qadamni ham ochadi
        # (`exam/access/` -> WebView), ya'ni operator uchun bu
        # oqimning davomi.
        self.confirm_btn = QPushButton("Davom etish")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setStyleSheet(primary_button_style(48))
        self.confirm_btn.clicked.connect(self._on_confirm_identity)
        self.identity_card.body.addWidget(self.confirm_btn)
        self.identity_card.setVisible(False)
        # Ko'rinish o'zgarishini kuzatamiz (`eventFilter`).
        self.identity_card.installEventFilter(self)
        side.addWidget(self.identity_card)

        self.message = MessageBar()
        side.addWidget(self.message)

        self.retry_btn = QPushButton("Qaytadan urinish")
        self.retry_btn.setProperty("variant", "ghost")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.clicked.connect(self.restart_matching)
        self.retry_btn.setVisible(False)
        self.retry_btn.installEventFilter(self)
        side.addWidget(self.retry_btn)

        # "SESSIYA TIRIK" KARTASI (`_enter_resume`). Kuzatuv rad
        # etilib shu sahifaga qaytilganda yuz ALLAQACHON tasdiqlangan va
        # sessiya serverda ochiq: yana solishtirishdan foyda yo'q (bir
        # martalik challenge sarflangan), kerakli amallar esa boshqa.
        self.resume_card = Card()
        self.resume_card.body.setContentsMargins(20, 16, 20, 16)
        self.resume_card.body.setSpacing(8)
        self.start_btn = QPushButton("Imtihonni boshlash")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet(primary_button_style(48))
        self.start_btn.clicked.connect(self._on_resume_start)
        self.resume_card.body.addWidget(self.start_btn)
        self.check_btn = QPushButton("Kamerani tekshirish")
        self.check_btn.setProperty("variant", "ghost")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.clicked.connect(self.camera_check_requested.emit)
        self.resume_card.body.addWidget(self.check_btn)
        self.abandon_btn = QPushButton("Boshqa talabgor")
        self.abandon_btn.setProperty("variant", "ghost")
        self.abandon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.abandon_btn.clicked.connect(self._on_abandon)
        self.resume_card.body.addWidget(self.abandon_btn)
        self.resume_card.setVisible(False)
        self.resume_card.installEventFilter(self)
        side.addWidget(self.resume_card)
        side.addStretch()

        body.addWidget(side_panel, 0)
        root.addLayout(body)

        self.overlay = BusyOverlay(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self._fit_photo()

    def eventFilter(self, watched, event):
        """
        Yon ustunda karta paydo bo'lsa — rasmga qoladigan joy o'zgaradi.

        Qt vidjet ko'rinishi o'zgarganini ota-onaga bildirmaydi, shu
        sababli tasdiq kartasi va "Qaytadan urinish" tugmasi
        kuzatiladi: ularni yoqadigan o'n uchta joyni alohida
        chaqiruvga aylantirish o'n uchta unutilishi mumkin bo'lgan
        joy degani bo'lardi.
        """
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self._fit_photo()
        return super().eventFilter(watched, event)

    def _fit_photo(self) -> None:
        """
        Hujjat rasmini EKRAN BALANDLIGIGA moslaydi (nisbat 3:4).

        Ramka qat'iy 264x352 bo'lganda past ekranda (1366x768,
        imtihon markazlarida odatiy) yon ustun sig'masdi. Qt bunday
        holatda yetishmagan joyni O'RALADIGAN YORLIQLARDAN oladi
        (ular layout'ga bir qatorlik minimum beradi) va natijada ism
        rasmning ustiga chiziladi — ekranda u "dastur buzildi"
        bo'lib ko'rinadi.
        """
        # Sahifa hali qurilmagan bo'lsa (`resizeEvent` konstruktordan
        # oldin ham kelishi mumkin) o'lchaydigan narsa yo'q.
        card = self.photo.parentWidget()
        if card is None or card.height() <= 0:
            return
        self._refit_wrapped()

        # JOY YETMASA IKKILAMCHI CHIPLAR YASHIRINADI.
        #
        # 1366x768 ekranda shaxs tasdig'i kartasi ochilganda yon
        # ustunga hamma narsa sig'maydi va tanlov aniq: bu qadamda
        # kartaning vazifasi — hujjat rasmini jonli kadr bilan
        # SOLISHTIRISH. Test vaqti allaqachon o'qilgan, "solishtirish
        # rejimi" esa moslik tasdiqlangandan keyin hech nima
        # qo'shmaydi. Rasmni pochta markasiga aylantirish esa aynan
        # shu qadamni ma'nosiz qilardi.
        self._apply_compact(card)

        # O'LCHOV KARTANING O'ZIDAN olinadi, ekran balandligidan
        # emas. Kartaga qancha joy tekkanini yon ustun hal qiladi
        # (xabar satri paydo bo'lsa kamayadi), qat'iy konstanta esa
        # shriftga va DPI masshtabiga bog'liq bo'lardi — 125% da
        # yana buzilardi.
        #
        # Ayirma — rasmdan BOSHQA hamma narsaning minimumi: rasm
        # shundan qolganini oladi va shu tufayli karta minimumi
        # kartaning o'ziga aynan teng bo'ladi, ya'ni Qt endi joy
        # "o'g'irlashi" kerak emas.
        #
        # UCH URINISH: rasm o'lchami o'zgargach yon ustun qaytadan
        # taqsimlanadi va kartaga tekkan balandlik ham o'zgaradi
        # (masalan xabar satri bitta qator o'rniga ikkitasini oladi).
        # Bitta o'tish bu yangi holatni ko'rmasdi, cheksiz sikl esa
        # kerak emas — har o'tishda ayirma kamayadi.
        for _ in range(3):
            others = card.layout().minimumSize().height() - self.photo.height()
            height = max(
                _PHOTO_MIN_HEIGHT, min(_PHOTO_HEIGHT, card.height() - others)
            )
            # Nisbat 3:4 — hujjat rasmi aynan shunday keladi.
            if height == self.photo.height():
                break
            self.photo.set_size(round(height * 3 / 4), height)
            self._side_panel.layout().activate()

    def _apply_compact(self, card) -> None:
        """
        Joy yetmasa ikkilamchi chiplarni yashiradi (`_fit_photo`).

        Qaror chiplar KO'RINGANDAGI o'lchov bo'yicha qabul qilinadi
        (yashirilganlarining balandligi ayirmaga QAYTA qo'shiladi),
        aks holda "yashirdim -> joy paydo bo'ldi -> ko'rsatdim ->
        joy yetmadi" degan tebranish yuzaga kelardi va chiplar har
        o'lchamda bir marta miltillardi.
        """
        hidden = 0
        if self._duration_text and not self.duration_badge.isVisible():
            hidden += self.duration_badge.sizeHint().height()
        if not self.mode_badge.isVisible():
            hidden += self.mode_badge.sizeHint().height()
        # Chiplar ko'ringandagi holat: qaror shundan chiqadi.
        others = card.layout().minimumSize().height() - self.photo.height() + hidden
        tight = card.height() - others < _PHOTO_MIN_HEIGHT

        self.duration_badge.setVisible(bool(self._duration_text) and not tight)
        self.mode_badge.setVisible(not tight)

    def _refit_wrapped(self) -> None:
        """
        O'raladigan yorliqlarga HAQIQIY balandligini beradi.

        `QLabel` ikki qatorga o'ralganda ham layout'ga BIR QATORLIK
        minimum beradi. Shu sababli yuqoridagi ayirma yetishmagan
        joyni ko'rmasdi va Qt o'sha joyni aynan shu yorliqlardan
        "o'g'irlab", ismni rasmning ustiga chizardi (bir xil tuzoq
        modal dialoglarda ham bor — `ui/dialogs/base.py:refit`).
        """
        for label in (self.name_label,):
            policy = label.sizePolicy()
            policy.setHeightForWidth(True)
            label.setSizePolicy(policy)
            width = label.width() or _SIDE_WIDTH
            label.setMinimumHeight(label.heightForWidth(max(1, width)))

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Sahifaga kirilganda: kamera + etalon."""
        candidate = self._state.candidate
        staff = self._state.staff
        if candidate is None:
            return

        exam = self._state.selected_exam
        device = self._state.device
        tooltips, captions = ip_chip_hints(self._state.machine.get("ips"))
        self.header.set_title(exam.name if exam else "Test tanlanmagan")
        self.header.set_seat(device)
        self.header.set_chips(
            region=staff.region_name if staff else "",
            zone=device.zone_name,
            ip=self._state.machine.get("ip", ""),
            tooltips=tooltips,
            captions=captions,
        )
        # CHEGARA IMTIHONNIKI. `AppState.config` "Davom etish"
        # bosilganda yuklangan imtihon profili
        # (`client/exam/config/?exam=`), ya'ni bu yerda global
        # standart emas, aynan shu imtihonning talabi turadi.
        # Server ham xuddi shu qiymatni qo'llaydi - ikkalasi
        # ajralib ketsa, client 70 ni kutib turar, server esa 85
        # bilan rad etardi va farqni faqat log'dan topish mumkin
        # bo'lardi.
        face_config = (self._state.config or {}).get("face") or {}
        try:
            self._threshold = int(face_config.get("min_score_initial"))
        except (TypeError, ValueError):
            self._threshold = _fallback_threshold()
        # Oqim qoidalari ham AYNAN SHU profildan: bir binoda ikki xil
        # sanoq yoki "necha kadrdan keyin rad" bir xil talabgorga ikki
        # xil natija berardi (`runtime_settings` izohi).
        config = self._state.config
        self._guide_seconds = runtime_settings.get(config, "face.guide_seconds")
        self._match_streak = runtime_settings.get(config, "face.match_streak")
        self._fail_streak_limit = runtime_settings.get(config, "face.fail_streak")
        self._fail_min_seconds = runtime_settings.get(config, "face.fail_min_seconds")

        # Platforma F.I.Sh. bermasligi mumkin - o'shanda niqoblangan
        # JSHSHIR ko'rinadi (`Candidate.display_name`).
        self.name_label.setText(candidate.display_name)
        self.pinfl_label.setText(candidate.masked_pinfl or "-")
        # Vaqt kelmagan bo'lsa chip UMUMAN ko'rinmaydi: bo'sh chip
        # "ma'lumot yo'qoldi" degan taassurot berardi.
        duration = self._duration_text = candidate.duration_label
        self.duration_badge.setText("Test vaqti: {}".format(duration))
        self.duration_badge.setToolTip(
            "Platforma bergan qiymat: {} daqiqa".format(candidate.duration_minutes)
            if duration
            else ""
        )
        self.duration_badge.setVisible(bool(duration))
        self._load_photo(candidate.photo_base64)

        self._reset_matching_state()
        self.identity_card.setVisible(False)
        self.resume_card.setVisible(False)
        self.retry_btn.setVisible(False)
        self.message.clear_message()

        if not self._engine.is_ready:
            self.message.show_message(
                "Yuz aniqlash modeli hali yuklanmoqda. Bir necha soniya kuting.",
                "warning",
            )

        # Sanoq kamera ochilishidan OLDIN qo'yiladi: ishchi aniqlash
        # O'CHIQ holda yaratiladi va birinchi kadrdan boshlab hech
        # narsa tahlil qilinmaydi. Etalon esa shu vaqt ichida fonda
        # tayyorlanadi - sanoq uning kechikishini ham yashiradi.
        self._begin_guide()
        self._start_camera()
        self._prepare_reference(candidate.photo_base64)
        # Sahifa endi to'lgan: rasm qolgan joyga moslanadi. Faqat
        # `resizeEvent` ga tayanib bo'lmaydi — u sahifa ochilishidan
        # oldin keladi va o'shanda yon ustun hali o'lchamsiz.
        self._fit_photo()

    def cleanup(self) -> None:
        """Kamerani to'xtatadi. Sahifadan chiqishda MAJBURIY."""
        self._guide_timer.stop()
        self._guide_state = "done"
        retire_camera(self._camera)
        self._camera = None
        self.camera_view.clear_view()

    def take_camera(self) -> Optional[CameraWorker]:
        """
        Kamerani keyingi sahifaga UZATADI (davriy FaceID uchun).

        Kamerani yopib qayta ochish Windows'da 2-4 soniya oladi va shu
        vaqt ichida talabgor kuzatuvsiz qoladi. Shuning uchun worker
        to'xtatilmaydi - egalik WebView sahifasiga o'tadi.
        """
        camera = self._camera
        if camera is not None:
            try:
                camera.frame_ready.disconnect(self._on_frame)
                camera.face_result.disconnect(self._on_face)
                camera.camera_error.disconnect(self._on_camera_error)
            except TypeError:
                pass
            # Keyingi sahifa (davriy FaceID) aniqlashga TAYANADI.
            # Kamera odatda sanoq tugagach uzatiladi, lekin bu shart
            # ishchining o'zida kafolatlanmasa, o'chiq aniqlash bilan
            # uzatilgan kamera test davomida jimgina "yuz yo'q" berardi.
            camera.set_detection_enabled(True)
        self._guide_timer.stop()
        self._camera = None
        return camera

    def _start_camera(self) -> None:
        if self._camera is not None:
            return
        # PARENT BERILMAYDI: Qt ota-obyekt yo'q qilinganda bolalarini ham
        # yo'q qiladi, ishlab turgan QThread yo'q qilinsa esa dastur
        # qulaydi. Egalik Python referensi orqali boshqariladi
        # (`retire_camera` ga qarang).
        # QURILMA ROL BO'YICHA OLINADI. Tekshiruv sahifasida qaysi
        # kamera "yuz tekshiruvi" deb tanlangan bo'lsa, o'sha ochiladi
        # (`AppState.cameras` -> `source_for_role`). Ilgari bu yerda
        # `CameraWorker()` turardi va u har doim `CAMERA_INDEX` (0) ni
        # ochardi — ya'ni operator kameralarni almashtirsa, shaxs
        # tekshiruvi stolga qaragan kameradan ketardi.
        source = source_for_role(
            self._state.cameras,
            "primary",
            stream_url_provider=self._repo.camera_stream,
        )
        if source is None:
            log.warning(
                "Taqsimotda yuz kamerasi yo'q — zaxira qurilma ochiladi"
            )
        self._camera = CameraWorker(source=source, detect=self._guide_state == "done")
        self.camera_label.setText(self._camera.label)
        self._camera.frame_ready.connect(self._on_frame)
        self._camera.face_result.connect(self._on_face)
        self._camera.camera_error.connect(self._on_camera_error)
        self._camera.start()

    # ------------------------------------------------------------------
    # Etalon
    # ------------------------------------------------------------------
    def _load_photo(self, photo_base64: str) -> None:
        if not photo_base64:
            self.photo.set_image_bytes(b"")
            return
        try:
            self.photo.set_image_bytes(base64.b64decode(photo_base64, validate=False))
        except (binascii.Error, ValueError):
            self.photo.set_image_bytes(b"")

    def _prepare_reference(self, photo_base64: str) -> None:
        """Etalon embedding - fon thread'ida (model chaqiruvi bloklovchi)."""
        self._reference = None
        self._reference_ready = False
        if not photo_base64:
            # Rasm umuman kelmadi va "rasm keldi, lekin yuz topilmadi"
            # bilan bir xil yakun beradi — shuning uchun bitta yo'ldan
            # o'tadi: nishon ham, xabar ham o'sha yerda.
            self._on_reference_ready(None)
            return

        self._set_mode_badge(None)
        worker = ApiWorker(self._engine.embed_base64, photo_base64, parent=self)
        worker.succeeded.connect(self._on_reference_ready)
        worker.failed.connect(lambda message, code: self._on_reference_ready(None))
        self._workers.run(worker)

    def _on_reference_ready(self, embedding) -> None:
        self._reference = embedding if isinstance(embedding, np.ndarray) else None
        self._reference_ready = True
        self._set_mode_badge(self._reference is not None)
        if self._reference is not None:
            return

        # Etalonsiz solishtirib bo'lmaydi. Enrollment o'chirilgan
        # (`_ENROLLMENT_ENABLED`), ya'ni bu TO'SIQ: sabab platformada
        # yoki rasm sifatida va uni operator tuzata olmaydi.
        self.message.show_message(
            "Hujjat rasmi yo'q yoki undan yuz olinmadi — bu talabgorni "
            "tekshirib bo'lmaydi. Administratorga murojaat qiling."
            if not _ENROLLMENT_ENABLED
            else "Hujjat rasmidan yuz olinmadi - tekshiruv operator zimmasida.",
            "error" if not _ENROLLMENT_ENABLED else "warning",
        )

    def _set_mode_badge(self, has_reference: Optional[bool]) -> None:
        # Matn QISQA: nishon tor ustunda turadi va uzun matn
        # kesilib qolardi ("Hujjat rasmi bilan solishtirila...").
        if has_reference is None:
            self.mode_badge.setText("Etalon tayyorlanmoqda…")
            self.mode_badge.setStyleSheet(badge_style("muted"))
        elif has_reference:
            self.mode_badge.setText("Hujjat rasmi bilan solishtiriladi")
            self.mode_badge.setStyleSheet(badge_style("info"))
        elif _ENROLLMENT_ENABLED:
            self.mode_badge.setText("Etalonsiz — yuz qayd etiladi")
            self.mode_badge.setStyleSheet(badge_style("warning"))
        else:
            self.mode_badge.setText("Hujjat rasmi yo'q — tekshirib bo'lmaydi")
            self.mode_badge.setStyleSheet(badge_style("error"))

    # ------------------------------------------------------------------
    # Kadr oqimi
    # ------------------------------------------------------------------
    def _on_frame(self, frame) -> None:
        self._last_frame = frame
        if self._guide_state == "waiting":
            # Kamera haqiqatan ishladi - endi talabgor o'zini ko'radi.
            # Sanoq kadr CHIZILISHIDAN OLDIN boshlanadi: birinchi
            # kadrning o'zi oval bilan chiqadi.
            self._start_countdown()
        self.camera_view.set_frame(frame)

    # ------------------------------------------------------------------
    # Yuzni joylashtirish (oval + sanoq)
    # ------------------------------------------------------------------
    def _begin_guide(self) -> None:
        """
        Yangi urinish oldidan: aniqlash o'chadi, sanoq kadrni kutadi.

        HAR URINISHDA qaytadan - "Qaytadan urinish" ham yangi urinish:
        talabgor odatda o'rnidan qimirlagan bo'ladi va birinchi
        urinishdagi joylashuvga tayanib bo'lmaydi.
        """
        self._guide_timer.stop()
        if self._guide_seconds <= 0:
            self._guide_state = "done"
            if self._camera is not None:
                self._camera.set_detection_enabled(True)
            # Sanoq o'chiq bo'lsa ham OVAL QOLADI: ekranda yuz ramkasi
            # yo'q va holatni (mos / mos emas / yaqinroq) aynan oval
            # rangi ko'rsatadi.
            self.camera_view.end_guide()
            return
        self._guide_state = "waiting"
        if self._camera is not None:
            self._camera.set_detection_enabled(False)
            # Kamera allaqachon ishlayapti (qayta urinish): sanoq
            # keyingi kadrda boshlanadi.

    def _start_countdown(self) -> None:
        duration_ms = self._guide_seconds * 1000
        self._guide_state = "countdown"
        self.camera_view.start_guide(duration_ms)
        self._guide_timer.start(duration_ms)
        self._update_state_badge("guide")
        self.score_label.setText("O'xshashlik: -")

    def _finish_guide(self) -> None:
        """Sanoq tugadi - aniqlash va solishtirish SHU YERDAN boshlanadi."""
        if self._guide_state != "countdown":
            return
        self._guide_state = "done"
        self.camera_view.end_guide()
        if self._camera is not None:
            self._camera.set_detection_enabled(True)
        self._update_state_badge("checking")

    def _on_camera_error(self, message: str) -> None:
        # Kamera to'xtadi - sanoq ham to'xtaydi. Aks holda taymer
        # "tekshiruv boshlandi" deb, kadrsiz ekranda holatni
        # almashtirib qo'yardi.
        self._guide_timer.stop()
        self._guide_state = "waiting"
        self.camera_view.end_guide(keep_hint=False)
        self.message.show_message(message, "error")
        self.state_badge.setText("Kamera xatosi")
        self.state_badge.setStyleSheet(badge_style("error"))

    def _on_face(self, result: dict) -> None:
        if self._guide_state != "done":
            # Sanoq paytida ishchi aniqlamaydi, lekin sanoq boshlanishidan
            # OLDIN navbatga tushgan natija (qayta urinishda ishchi hali
            # yoqiq edi) shu yerga yetib kelishi mumkin. U qarorga ham,
            # ekranga ham tushmasligi kerak.
            return
        # EKRANDA YUZ RAMKASI YO'Q: holatni oval rangi, ballni esa
        # oval tepasidagi yozuv ko'rsatadi (`CameraView`). Shuning
        # uchun natijadan koordinatalar olinmaydi.
        state = result.get("state")

        if self._verifying or self._verified or self._failed:
            # HOLAT YANGILANISHDA DAVOM ETADI, qaror esa endi qabul
            # qilinmaydi.
            #
            # Ilgari bu yerda `return` turardi va natijada ekrandagi
            # belgi oxirgi holatida MUZLAB qolardi. Operator uchun bu
            # "dastur qotib qoldi" degan taassurot berardi, holbuki
            # sessiya ochilib, hujjat tasdig'i kutilayotgan bo'lardi.
            # Urinish yopilgan bo'lsa oval QIZIL qoladi: yashil oval
            # "hammasi joyida" degan noto'g'ri xabar berardi, holbuki
            # ekranda "mos kelmadi" yozuvi turibdi.
            # BALL QAYSI BIRI KO'RSATILADI. Tasdiqlanganda -
            # sessiyani ochgani, ya'ni serverdagi yozuv bilan AYNAN
            # bir xil son. Muvaffaqiyatsiz urinishda esa eng
            # yuqorisi: serverga ham o'sha ketgan
            # (`_report_failed_attempt`) va xabarda ham "eng yuqori
            # o'xshashlik" deb ataladi.
            if self._verified:
                state_hint = "match"
                shown = self._verified_score
            elif self._failed:
                state_hint = "mismatch"
                shown = self._best_score
            else:
                state_hint = "ok"
                shown = self._verified_score
            self.camera_view.set_detection(state_hint, shown or None)
            return

        if state != "ok":
            # Yuz yo'q / uzoq / bir nechta - SOLISHTIRIB BO'LMAYDI,
            # ya'ni bu "mos kelmadi" ham emas. Ikkala seriya ham
            # uziladi: aks holda kadrga kirib-chiqib turgan talabgor
            # bir necha daqiqada "kira olmadi" bo'lib qolardi.
            self._streak = 0
            self._fail_streak = 0
            self._fail_since = 0.0
            self.camera_view.set_detection(state)
            self._update_state_badge(state)
            return

        embedding = result.get("embedding")
        self._last_embedding = embedding

        if not self._reference_ready:
            self.camera_view.set_detection("ok")
            self._update_state_badge("waiting_reference")
            return

        if self._reference is None:
            if not _ENROLLMENT_ENABLED:
                # Solishtiradigan etalon yo'q va enrollment o'chirilgan:
                # oqim shu yerda TO'XTAYDI. Kadrni qabul qilib
                # yuborish tekshiruvning o'zini bekor qilardi.
                self.camera_view.set_detection("ok")
                self._update_state_badge("no_reference")
                return
            # Enrollment: solishtirish yo'q, sifatli kadr yetarli.
            self._streak += 1
            self.camera_view.set_detection("ok")
            self._update_state_badge("enroll")
            if self._streak >= self._match_streak:
                self._submit_face(embedding, score=None)
            return

        # SOLISHTIRISH SHU YERDA: ikkala embedding ham clientda.
        # Chegara esa imtihonga biriktirilgan sozlamadan
        # (`config.face.min_score_initial`) - server ham aynan
        # o'shani qo'llaydi.
        score = self._engine.compare(self._reference, embedding)
        self._best_score = max(self._best_score, score)
        self.score_label.setText(
            "O'xshashlik: {}% (talab {}%)".format(score, self._threshold)
        )

        if score >= self._threshold:
            self._streak += 1
            self._fail_streak = 0
            self._fail_since = 0.0
            self.camera_view.set_detection("match", score)
            self._update_state_badge("match")
            if self._streak >= self._match_streak:
                self._submit_face(embedding, score=score)
        else:
            self._streak = 0
            self._fail_streak += 1
            if self._fail_since == 0.0:
                self._fail_since = time.monotonic()
            self.camera_view.set_detection("mismatch", score)
            self._update_state_badge("mismatch")
            # Ketma-ket uzoq mos kelmaslik - endi bu o'tkinchi holat
            # emas. Urinish yopiladi va DALIL serverga ketadi: kadrda
            # boshqa odam turgan bo'lishi mumkin.
            #
            # IKKALA shart ham kerak (kadr soni VA vaqt): tez kamerada
            # 15 kadr atigi 2-3 soniya bo'ladi va ko'zoynagini
            # to'g'rilayotgan haqiqiy talabgor ham "kira olmadi"
            # bo'lib qolardi.
            elapsed = time.monotonic() - self._fail_since
            if (
                self._fail_streak >= self._fail_streak_limit
                and elapsed >= self._fail_min_seconds
            ):
                self._report_failed_attempt(self._best_score)

    def _update_state_badge(self, state: str) -> None:
        mapping = {
            "none": ("Yuz topilmadi", "muted"),
            "far": ("Yaqinroq keling", "warning"),
            "multiple": ("Kadrda bir nechta odam", "error"),
            "mismatch": (
                "Mos kelmadi ({}/{})".format(self._fail_streak, self._fail_streak_limit),
                "error",
            ),
            "match": ("Mos keldi ({}/{})".format(self._streak, self._match_streak), "success"),
            "enroll": (
                "Yuz qayd etilmoqda ({}/{})".format(self._streak, self._match_streak), "info"
            ),
            "waiting_reference": ("Etalon kutilmoqda", "muted"),
            "no_reference": ("Hujjat rasmi yo'q", "error"),
            "failed": ("Mos kelmadi", "error"),
            "guide": ("Yuzni oval ichiga joylang", "info"),
            "checking": ("Tekshirilmoqda", "info"),
        }
        text, kind = mapping.get(state, ("Kutilmoqda", "muted"))
        self.state_badge.setText(text)
        self.state_badge.setStyleSheet(badge_style(kind))

    # ------------------------------------------------------------------
    # Backend
    # ------------------------------------------------------------------
    def _frame_jpeg(self) -> Optional[bytes]:
        """
        Serverga yuboriladigan JONLI KADR.

        TO'LIQ KADR, yuz qirqimi emas: dalilning qiymati aynan
        kontekstda - kadrda ikkinchi odam bormi, talabgor telefonga
        qaraydimi. Qirqim bu savollarning hech biriga javob bermasdi.

        Kadr bo'lmasa `None` qaytadi va so'rov rasmsiz ketadi: rasm
        dalil, to'siq emas.
        """
        if self._last_frame is None:
            return None
        try:
            data = encode_jpeg(self._last_frame)
        except Exception:
            log.warning("Kadrni JPEG ga o'girib bo'lmadi", exc_info=True)
            return None
        return data or None

    def _reference_jpeg(self) -> Optional[bytes]:
        """
        Platformadan kelgan hujjat rasmi (xom baytlar).

        QAYTA KODLANMAYDI: platforma bergan JPEG o'z holicha
        yuboriladi. Uni qayta siqish sifatni bekorga pasaytirardi -
        panelda esa aynan shu rasm operatorning ko'ziga ko'rinadi.
        """
        candidate = self._state.candidate
        raw = getattr(candidate, "photo_base64", "") if candidate else ""
        if not raw:
            return None
        try:
            return base64.b64decode(raw, validate=False) or None
        except (binascii.Error, ValueError):
            log.warning("Etalon rasm base64 emas - yuborilmaydi")
            return None

    def _submit_face(self, embedding, score: Optional[int]) -> None:
        candidate = self._state.candidate
        if candidate is None or self._verifying:
            return
        self._verifying = True
        # QAROR QABUL QILINDI - ball shu yerda MUZLAYDI.
        #
        # Bundan keyin solishtirish umuman bajarilmaydi (yuqoridagi
        # erta qaytish), ya'ni ekrandagi son o'zgarmaydi. Bu ataylab:
        # sessiyani ochgan ball dalil bo'lib serverga ketdi va
        # ekranda undan keyin yugurib turgan son "nega 47% da
        # kiritdi?" degan javobsiz savol tug'dirardi. Yozuv esa
        # sonning MUZLAGANINI ochiq aytadi ("Tasdiqlandi: 66%") -
        # aks holda u jonli o'lchov bo'lib ko'rinardi.
        self._verified_score = score
        if score is not None:
            self.score_label.setText(
                "Tasdiqlandi: {}% (talab {}%)".format(score, self._threshold)
            )
        self.overlay.start("Sessiya ochilmoqda...")

        worker = ApiWorker(
            self._repo.verify_face,
            challenge=candidate.challenge,
            embedding=[float(value) for value in embedding],
            score=score,
            faces_detected=1,
            image=self._frame_jpeg(),
            # HUJJAT RASMI HAM KETADI va faqat shu yerda (kirish
            # tekshiruvi). Panelda ballning o'zi hech narsani
            # isbotlamaydi: apellyatsiyada hujjatdagi odam va
            # kameradagi odam yonma-yon kerak bo'ladi. Rasm
            # allaqachon xotirada - platformadan kelgan va
            # solishtirishga ishlatilgan.
            reference_image=self._reference_jpeg(),
            parent=self,
        )
        # Etalon SESSIYAGA o'tadi: test davomidagi solishtirish aynan
        # shu vektorga nisbatan bo'ladi (serverdagi `reference_embedding`
        # ham shu). Javob kelmasdan yozmaymiz - sessiya ochilmasa,
        # etalonning ham ma'nosi yo'q.
        self._pending_reference = embedding
        worker.succeeded.connect(self._on_session_created)
        worker.failed.connect(self._on_verify_failed)
        self._workers.run(worker)

    def _report_failed_attempt(self, score: int) -> None:
        """
        Urinish MUVAFFAQIYATSIZ: rasm va ball serverga ketadi.

        Sessiya ochilmaydi va `challenge` sarflanmaydi - operator
        "Qaytadan urinish" ni bosib yangi urinish boshlashi mumkin.
        Har urinish uchun BITTA so'rov: har kadrda yuborish
        `FaceVerifyThrottle` ni bir zumda yeb qo'yardi va bir xil
        rasmni o'nlab marta diskka yozardi.
        """
        candidate = self._state.candidate
        if candidate is None or self._failed:
            return
        self._failed = True
        self._update_state_badge("failed")
        # "Eng yuqori" - aynan shu son serverga ketadi va xabarda ham
        # shunday ataladi. Oxirgi kadrniki qolsa, ekranda ikkita,
        # panelda uchinchi raqam bo'lardi.
        self.score_label.setText(
            "Eng yuqori: {}% (talab {}%)".format(score, self._threshold)
        )
        self.camera_view.set_detection("mismatch", score)

        worker = ApiWorker(
            self._repo.face_attempt,
            challenge=candidate.challenge,
            score=score,
            faces_detected=1,
            image=self._frame_jpeg(),
            # Aynan MOS KELMAGAN urinishda ikkita rasm eng qimmatli:
            # "kadrda kim turgan edi?" degan savolga faqat shu
            # juftlik javob beradi.
            reference_image=self._reference_jpeg(),
            parent=self,
        )
        worker.succeeded.connect(self._on_attempt_recorded)
        worker.failed.connect(self._on_attempt_failed)
        self._workers.run(worker)

    def _on_attempt_recorded(self, payload) -> None:
        """
        Xabar IKKI XIL bo'ladi va farq operator uchun hal qiluvchi.

        Chegaradan biroz past ball — sifat masalasi: yorug'lik,
        burchak, ko'zoynak. Chegaradan ANCHA past ball esa boshqa
        savolni beradi: kadrdagi odam umuman shu talabgormi? Bitta
        umumiy matn ("kameraga to'g'ri qarang") ikkinchi holatda
        operatorni yo'q nosozlikni qidirishga majbur qilardi —
        kamerani qanchalik to'g'rilamasin, boshqa odamning yuzi
        hujjatdagi rasmga mos kelmaydi.
        """
        data = payload or {}
        score = int(data.get("score") or 0)
        threshold = int(data.get("threshold") or self._threshold)
        attempts = int(data.get("attempts") or 0)

        if score <= threshold - _FAR_MISS_GAP:
            hint = (
                "Kadrdagi odam hujjatdagi rasmga umuman o'xshamadi — JSHSHIR "
                "to'g'ri kiritilganini va talabgor o'zi ekanini tekshiring."
            )
        else:
            hint = (
                "Biroz yetmadi — yorug'likni va kamera burchagini to'g'rilang, "
                "ko'zoynak yoki niqobni yechib qaytadan urinib ko'ring."
            )

        self.message.show_message(
            "Yuz mos kelmadi: eng yuqori o'xshashlik {}%, talab {}%. "
            "{}-urinish. {}".format(score, threshold, attempts, hint),
            "error",
        )
        self.retry_btn.setVisible(True)

    def _on_attempt_failed(self, message: str, code: str) -> None:
        # Yozuvni serverga yetkazib bo'lmadi. Oqim BARIBIR to'xtaydi:
        # mos kelmaganini operator ekranda ko'rib turibdi va uni
        # tarmoq xatosi tufayli davom ettirish noto'g'ri bo'lardi.
        log.warning("Urinishni qayd etib bo'lmadi (%s): %s", code or "-", message)
        self.message.show_message(
            "Yuz mos kelmadi. Qaytadan urinib ko'ring.", "error"
        )
        self.retry_btn.setVisible(True)

    def _on_session_created(self, payload) -> None:
        session = ProctoringSession.from_api(payload or {})
        self._state.session = session
        self._verified = True
        # Test davomidagi solishtirish uchun ETALON. Sahifalar
        # bir-biriga to'g'ridan-to'g'ri murojaat qilmaydi, shuning
        # uchun u `AppState` orqali uzatiladi.
        self._state.face_reference = self._pending_reference

        # Sessiya tokeni endi HAR SO'ROVGA qo'shiladi - `exam/access/`,
        # heartbeat va hodisalar aynan shu bilan ishlaydi.
        from services.api_client import ApiClient

        ApiClient().set_session_token(session.token)

        self.message.show_message("Tasdiqlandi", "success")
        self.state_badge.setText("Tasdiqlandi")
        self.state_badge.setStyleSheet(badge_style("success"))

        # Shaxs tasdig'i talab qilinmasa - to'g'ridan-to'g'ri imtihonga.
        # Talab qilinsa, backend `identity_not_confirmed` qaytaradi va
        # o'shanda hujjat formasi ochiladi.
        self._request_access()

    def _on_verify_failed(self, message: str, code: str) -> None:
        self._verifying = False
        self._streak = 0
        # URINISH YOPILADI - yangisi faqat "Qaytadan urinish" bilan.
        # Ilgari bayroq qo'yilmasdi va keyingi mos kadr so'rovni yana
        # yuborardi: rad javobidan keyin har ~300 ms da yangi
        # `face/verify/` (log'da yuzlab 404), holbuki server javobi
        # o'zgarmaydi.
        self._failed = True
        self.overlay.stop()
        log.info("FaceID rad etildi (%s): %s", code or "-", message)
        if code == "session_not_found":
            # Challenge muddati tugagan yoki sarflangan - bu sahifada
            # qayta urinishning ma'nosi yo'q, yangisini faqat JSHSHIR
            # tekshiruvi beradi.
            self.message.show_message(
                "Tekshiruv muddati tugagan. JSHSHIR ni qaytadan kiriting.", "error"
            )
            self.retry_btn.setText("Yangi talabgor")
        else:
            self.message.show_message(message, "error")
        self.retry_btn.setVisible(True)

    def _request_access(self) -> None:
        self.overlay.start("Imtihon ochilmoqda...")
        worker = ApiWorker(self._repo.exam_access, parent=self)
        worker.succeeded.connect(self._on_access_granted)
        worker.failed.connect(self._on_access_failed)
        self._workers.run(worker)

    def _on_access_granted(self, payload) -> None:
        self.overlay.stop()
        self._state.exam_access = payload or {}
        self.access_granted.emit(self._state.exam_access)

    def _on_access_failed(self, message: str, code: str) -> None:
        self.overlay.stop()
        self._verifying = False
        if code == "identity_not_confirmed":
            # Kutilgan holat: operator hujjatni tekshirishi kerak.
            #
            # HECH QANDAY MAYDONGA FOKUS BERILMAYDI: hujjat turi va
            # raqami formasi sahifadan olib tashlangan (operator
            # hujjatni EKRANDA solishtiradi). Ilgari bu yerda
            # `self.document_number.setFocus()` turardi va u
            # `AttributeError` bilan yiqilardi - ya'ni operator
            # tasdig'i talab qilingan HAR BIR sessiyada.
            self.identity_card.setVisible(True)
            self.confirm_btn.setFocus()
            # KO'RSATMA ENDI FAQAT SHU YERDA. Kartadagi tushuntirish
            # matni olib tashlandi, ya'ni "nima qilish kerak" degan
            # savolga javob beradigan yagona joy shu qator - shuning
            # uchun u tugma nomini AYNAN ataydi.
            self.message.show_message(
                "Yuz tasdiqlandi. Hujjatdagi rasmni jonli kadr bilan "
                "solishtiring va «Davom etish» ni bosing.",
                "info",
            )
            return
        self.message.show_message(message, "error")
        self.retry_btn.setVisible(True)

    # ------------------------------------------------------------------
    # Operator qarori
    # ------------------------------------------------------------------
    def _on_confirm_identity(self) -> None:
        # Hech qanday maydon tekshirilmaydi: qaror operatorning
        # ko'zi bilan qabul qilinadi va u tugmani bosishi bilan
        # rasmiylashadi. Kim tasdiqlagani serverda qayd etiladi.
        self.overlay.start("Tasdiqlanmoqda...")
        worker = ApiWorker(self._repo.confirm_identity, parent=self)
        worker.succeeded.connect(lambda _: self._on_identity_confirmed())
        worker.failed.connect(self._on_identity_failed)
        self._workers.run(worker)

    def _on_identity_confirmed(self) -> None:
        if self._state.session is not None:
            self._state.session.identity_confirmed = True
        self.identity_card.setVisible(False)
        self._request_access()

    def _on_identity_failed(self, message: str, code: str) -> None:
        self.overlay.stop()
        self.message.show_message(message, "error")

    def _on_reject(self) -> None:
        """
        Shaxsni RAD ETISH - hozircha UI'dan chaqirilmaydi.

        Tugma tasdiq kartasidan olib tashlandi (sabab modul
        docstring'ida). Kod QOLDIRILGAN: server endpoint'i joyida va
        rad etish oqimi (sessiyani chetlashtirish, tokenni bekor
        qilish, "Yangi talabgor" ga qaytish) qayta kerak bo'lsa
        tugmani ulash kifoya - uni noldan yozish esa boshqacha
        chiqardi. Xuddi shu naqsh `_ENROLLMENT_ENABLED` da ham.
        """
        self.overlay.start("Rad etilmoqda...")
        worker = ApiWorker(
            self._repo.reject_identity,
            reason="Hujjat talabgorga mos kelmadi",
            parent=self,
        )
        worker.succeeded.connect(lambda _: self._on_rejected())
        worker.failed.connect(self._on_identity_failed)
        self._workers.run(worker)

    def _on_rejected(self) -> None:
        self.overlay.stop()
        self.identity_card.setVisible(False)
        self.message.show_message(
            "Shaxs tasdiqlanmadi - sessiya chetlashtirildi.", "error"
        )
        self.retry_btn.setText("Yangi talabgor")
        self.retry_btn.setVisible(True)
        # Sessiya tokeni endi yaroqsiz - keyingi so'rovlarga qo'shilmasin.
        from services.api_client import ApiClient

        ApiClient().set_session_token(None)

    # ------------------------------------------------------------------
    # Sessiya tirik: kuzatuv rad etilgandan keyin
    # ------------------------------------------------------------------
    def _enter_resume(self) -> None:
        """
        Yuz tasdiqlangan, sessiya ochiq - faqat imtihonni qayta ochish.

        Kamera PREVIEW uchun ochiladi (u imtihon sahifasiga uzatilgan va
        o'sha yerda to'xtatilgan), solishtirish esa YOQILMAYDI:
        `_verified` saqlanadi va `_on_face` qaror qabul qilmaydi.
        """
        self.identity_card.setVisible(False)
        self.retry_btn.setVisible(False)
        self.resume_card.setVisible(True)
        self.state_badge.setText("Tasdiqlangan")
        self.state_badge.setStyleSheet(badge_style("success"))
        self.message.show_message(
            "Yuz tasdiqlangan, sessiya ochiq — qayta tekshirish kerak emas. "
            "Kamera tekshiruvi talab qilinsa «Kamerani tekshirish» ni, "
            "nosozlik tuzatilgan bo'lsa «Imtihonni boshlash» ni bosing.",
            "info",
        )
        self._guide_timer.stop()
        self._guide_state = "done"
        self.camera_view.end_guide()
        if self._camera is None:
            self.camera_view.clear_view()
            self._start_camera()
        self.start_btn.setFocus()

    def resume_start(self) -> None:
        """Kamera tekshiruvidan qaytildi - imtihon darhol qayta ochiladi."""
        self._enter_resume()
        self._on_resume_start()

    def _on_resume_start(self) -> None:
        self.resume_card.setVisible(False)
        self._request_access()

    def _on_abandon(self) -> None:
        """
        Talabgor imtihonni boshlamay ketdi - sessiya serverda YOPILADI.

        Ochiq qoldirilsa talabgor qulfi (`lock_candidate`) ~15 daqiqa
        (`close_stale_sessions`) turib qolardi va u boshqa kompyuterda
        ham kira olmasdi. `completed` YUBORILMAYDI: test topshirilmagan,
        ya'ni kompyuter broni saqlanadi (talabgor qaytib kelishi mumkin).
        """
        self.resume_card.setVisible(False)
        self.overlay.start("Sessiya yopilmoqda...")
        worker = ApiWorker(
            self._repo.finish_session, reason="Imtihon boshlanmadi (operator)", parent=self
        )
        worker.succeeded.connect(lambda _: self._after_abandon())
        worker.failed.connect(lambda message, code: self._after_abandon(message))
        self._workers.run(worker)

    def _after_abandon(self, error: str = "") -> None:
        from services.api_client import ApiClient

        if error:
            log.warning("Sessiyani yopib bo'lmadi: %s - uni server yopadi", error)
        self.overlay.stop()
        ApiClient().set_session_token(None)
        self._state.session = None
        self._reset_matching_state()
        self.back_requested.emit()

    # ------------------------------------------------------------------
    def restart_matching(self) -> None:
        """
        Qaytadan urinish: holat tozalanadi.

        Kamera odatda ishlab turadi, lekin HAR DOIM emas: kuzatuv rad
        etilib (`session_blocked`) shu sahifaga qaytilganda u
        allaqachon imtihon sahifasiga uzatilgan va o'sha yerda
        to'xtatilgan bo'ladi. O'shanda kamera QAYTA OCHILADI - aks
        holda sahifada qotib qolgan bo'sh kadr turardi va operator
        "Qaytadan urinish" natija bermayotganini tushunmasdi.
        """
        if self._state.session is not None and self._verified:
            # SESSIYA TIRIK: kuzatuv rad etilib qaytildi. Yuz qayta
            # SOLISHTIRILMAYDI - challenge `face/verify/` da sarflangan
            # va har urinish `session_not_found` (404) olardi.
            self._enter_resume()
            return
        if self._state.session is not None and not self._verified:
            self._state.session = None
        if self.retry_btn.text() == "Yangi talabgor":
            self.retry_btn.setText("Qaytadan urinish")
            self.back_requested.emit()
            return
        self._reset_matching_state()
        self.message.clear_message()
        self.retry_btn.setVisible(False)
        self._begin_guide()
        if self._camera is None:
            self.camera_view.clear_view()
            self._start_camera()

    def _reset_matching_state(self) -> None:
        self._streak = 0
        self._fail_streak = 0
        self._fail_since = 0.0
        self._best_score = 0
        self._verified_score = None
        self._verifying = False
        self._verified = False
        self._failed = False
        self._last_embedding = None
        self._pending_reference = None
        # Etalon ham bo'shatiladi: yangi urinish - yangi solishtiruv,
        # va oldingi urinishning vektori WebView sahifasiga o'tib
        # ketmasligi kerak.
        self._state.face_reference = None
        self.score_label.setText("O'xshashlik: -")
        self.state_badge.setText("Kutilmoqda")
        self.state_badge.setStyleSheet(badge_style("muted"))

    def shutdown(self) -> None:
        self.cleanup()
        self._workers.wait_all()
