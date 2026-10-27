"""
2-SAHIFA - Kuzatuv kameralari va testni tanlash.

Ro'yxat handshake bilan keladi (`AppState.exams`), shuning uchun
tanlov qismida tarmoq chaqiruvi YO'Q - u darhol ishlaydi. Yangilash
esa ochiq amal: sarlavhadagi BITTA ikonka handshake'ni qaytadan
bajaradi (kompyuter, bino, imtihonlar) va kameralarni qayta aniqlaydi.

USTUNLAR TARTIBI: kamera CHAPDA, tanlov O'NGDA.

Ilgari teskari edi va bu noto'g'ri o'qilardi. Operator bu ekranda
ikkita ish qiladi va ular teng emas: kamerani tekshirish - kun
boshida bir marta, uzoq va e'tibor talab qiladigan ish (kadrni ochish,
burchakni to'g'rilash); testni tanlash - har talabgor uchun ikki
bosish. G'arb yozuvida ko'z chapdan boshlanadi, ya'ni chap ustun
"avval nima qilinadi" degan savolga javob beradi. Kamera kengroq
ustunni ham oladi: unda ikkita video kadr turadi, tanlov qismida esa
ikkita ochiluvchi ro'yxat.

NIMA UCHUN KAMERA AYNAN SHU SAHIFADA. Oqimda kameraga bog'liq
birinchi qadam - FaceID (4-sahifa), ya'ni nosozlik o'sha yerda
chiqadi: operator talabgorni chaqirib, JSHSHIR kiritib, faqat
o'shanda "kamera ochilmadi" xabarini oladi va butun oqimni qaytadan
boshlaydi. Bu yerda esa talabgor hali kelmagan va nosozlikni tuzatish
uchun vaqt bor.

Kamera qarorlari SAHIFADA EMAS: rol taqsimoti
`proctoring/camera/roles.py` da (sof funksiya), oqim boshqaruvi
`ui/widgets/camera_panel.py` da. Bu yerda faqat ikkalasini bir
ekranda birlashtirish qoladi.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from proctoring import policy as policy_check
from services import system_info
from services.app_state import AppState, ExamOption
from services.workers import ApiWorker, WorkerHolder
from ui.dialogs.policy_dialog import PolicyDialog
from ui.styles import COLORS, primary_button_style
from ui.widgets.camera_panel import CameraPanel
from ui.widgets.header import WorkstationHeader, ip_chip_hints
from ui.widgets.indicators import Card
from ui.widgets.md3 import IconBadge, RippleButton, StatusIcon, elevate
from ui.widgets.notice import Notice

log = logging.getLogger(__name__)

#: Tanlov maydoni: MD3 "outlined text field" balandligi (~52 px). Global
#: qoidadagi `min-height: 44px` + chetlar 66 px berardi va ikki maydon
#: 1366x768 da tayyorgarlik ro'yxatiga joy qoldirmasdi.
_COMBO_QSS = "QComboBox { min-height: 28px; }"


class _ReadinessRow(QFrame):
    """
    Tayyorgarlik qatori: holat belgisi + nom + qisqa holat matni.

    Holat SHAKL va MATN bilan ham (✓ / ! / ✕ / nuqta), faqat rang emas.
    """

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("readinessRow")
        self.setStyleSheet(
            "QFrame#readinessRow {{ background-color: {}; border: none; "
            "border-radius: 12px; }}".format(COLORS["surface_container_low"])
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 12, 7)
        row.setSpacing(10)
        self.icon = StatusIcon("pending", 24)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        name = QLabel(title)
        name.setStyleSheet("font-size: 13px; font-weight: 700; color: {};".format(COLORS["text"]))
        texts.addWidget(name)
        self.detail = QLabel("—")
        self.detail.setStyleSheet(
            "font-size: 12px; color: {};".format(COLORS["on_surface_variant"])
        )
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)

        self._full = "—"
        # Uzun test nomi ustunni kengaytirmasin: matn kesiladi (`_elide`),
        # to'liqi tooltip'da.
        self.detail.setMinimumWidth(40)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    @property
    def status(self) -> str:
        return self.icon.status

    def set_state(self, status: str, detail: str) -> None:
        self.icon.set_status(status)
        self._full = detail
        self.detail.setToolTip(detail)
        self._elide()

    def _elide(self) -> None:
        width = max(40, self.detail.width())
        self.detail.setText(
            self.detail.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width)
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._elide()


def _scan_machine(*, threats: bool, peripherals: bool, allow=(),
                  allow_virtual_host: bool = False) -> dict:
    """
    "Davom etish" dagi mashina tekshiruvi - BITTA FON CHAQIRUVIDA.

    Ikki qism bir-biridan MUSTAQIL: tahdid skaneri yiqilsa ham tashqi
    xotira baribir tekshiriladi va aksincha. Ikkita alohida worker
    bo'lsa, `_finish_check` ikkalasini kutish uchun holat yig'ishi
    kerak edi; ketma-ket bajarish esa arzon - qurilmalar ~0.1 s.

    Qaytaradi: `{"threats": ThreatReport | None, "threat_error": str,
    "peripherals": [payload] | None}`.
    """
    result = {"threats": None, "threat_error": "", "peripherals": None}
    if threats:
        from services import threat_scanner

        try:
            result["threats"] = threat_scanner.sweep(
                allow=allow, allow_virtual_host=allow_virtual_host
            )
        except Exception as exc:  # noqa: BLE001 - qurilma tekshiruvi davom etsin
            log.warning("Tahdid skaneri qayta ishlamadi", exc_info=True)
            result["threat_error"] = type(exc).__name__
    if peripherals:
        from services import peripherals as peripheral_scan

        # ISTISNO TASHLAMAYDI - aniqlab bo'lmasa `None` (ogohlantirish yo'q).
        result["peripherals"] = peripheral_scan.scan_attached_storage()
    return result


def _machine_identity() -> dict:
    """
    Mashinaning MAC va LAN manzili — WinAPI orqali, bitta adapterdan.

    ALOHIDA FUNKSIYA va u fon thread'ida chaqiriladi: zaxira yo'lda
    OS buyrug'i ishga tushishi mumkin (`getmac`) va u sekin mashinada
    bir necha yuz millisekund oladi. UI thread'ida bu sarlavha
    chizilishini kechiktirardi.

    Qiymat keshdan keladi: handshake uni allaqachon o'lchagan va
    serverga yuborgan (`AuthService.handshake`). Shu tufayli
    sarlavhadagi MAC va server tekshirgan MAC — AYNAN bitta qiymat.
    Ikkitasini alohida o'lchash "ekranda bir xil, serverda boshqa"
    degan tushuntirib bo'lmaydigan holatni yaratardi.
    """
    return system_info.machine_identity()


class ExamSelectPage(QWidget):
    """Kuzatuv kameralari va imtihon tanlash."""

    exam_selected = pyqtSignal(object)  # ExamOption
    #: `MainWindow` ulanadi, lekin bu sahifada HECH NARSA emitlamaydi.
    #
    # Sarlavhadan "Chiqish" tugmasi ataylab olib tashlandi (sabab
    # `WorkstationHeader` docstring'ida). Signal saqlanadi: u oqimning
    # shartnomasi qismi va boshqa sahifalar undan foydalanadi.
    logout_requested = pyqtSignal()

    def __init__(self, state: AppState, repo, auth, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._repo = repo
        # `AuthService` handshake'ni bajaradi va natijani `AppState` ga
        # yozadi. Uni bu yerda takrorlash mumkin emas: u yerda
        # `DeviceNotRegistered` dan tiklanish mantig'i bor va ikkinchi
        # nusxa albatta undan ajralib ketardi.
        self._auth = auth
        self._workers = WorkerHolder()
        self._reloading = False
        #: Ekranda ko'rsatiladigan MAC va IP.
        #:
        #: `refresh()` uni faqat BO'SH bo'lganda so'raydi: qiymat
        #: handshake paytida o'lchanadi va keshlanadi
        #: (`system_info.machine_identity`), ya'ni har sahifa
        #: ochilishida qayta o'lchash bekorga ish bo'lardi. "Yangilash"
        #: esa keshni ataylab bo'shatadi - o'sha tugmaning butun
        #: ma'nosi "hozir holat qanday?" degan savolni QAYTADAN
        #: berish.
        self._identity: dict = {}
        #: Sozlama tekshiruvi ketayotgan imtihon.
        #
        # Saqlanadi, chunki javob FON thread'idan keladi va o'sha
        # paytda operator combo'da boshqa imtihonni tanlab qo'ygan
        # bo'lishi mumkin - tekshiruv esa SO'RALGAN imtihonga
        # tegishli bo'lishi kerak, ekranda ko'rinayotganiga emas.
        self._pending_exam = None
        #: "Mashina tanilmadi" dialogi (bitta nusxa, kerak bo'lganda).
        self._machine_dialog = None
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 22, 40, 22)
        root.setSpacing(14)

        # 1-bosqich oqim ko'rsatkichi bilan (`md3.FlowStepper`).
        self.header = WorkstationHeader(step=1)
        self.header.reload_requested.connect(self.reload_all)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(16)

        # --- Chap: kameralar (kengroq ustun) ---
        # `show_reload=False` - yangilash sarlavhada, bitta umumiy
        # ikonkada.
        self.camera_panel = CameraPanel(self._repo, show_reload=False)
        self.camera_panel.layout_resolved.connect(self._on_cameras_resolved)
        self.camera_panel.check_completed.connect(self._on_check_completed)
        body.addWidget(self.camera_panel, 3)

        # --- O'ng: tanlov ---
        body.addWidget(self._build_form_card(), 2)

        root.addLayout(body, 1)

    def _build_form_card(self) -> Card:
        card = Card()
        card.body.setContentsMargins(22, 18, 22, 20)
        card.body.setSpacing(10)
        # Soya FAQAT shu kartada: kamera kartasida jonli video bor va
        # `QGraphicsEffect` uni har kadrda qayta chizardi (`md3.elevate`).
        elevate(card)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(IconBadge("exam", 40), 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Test ma'lumotlari")
        title.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: {};".format(COLORS["on_surface"])
        )
        titles.addWidget(title)
        caption = QLabel("Imtihon turini va testni tanlang")
        caption.setStyleSheet("font-size: 12px; color: {};".format(COLORS["on_surface_variant"]))
        titles.addWidget(caption)
        top.addLayout(titles, 1)
        card.body.addLayout(top)
        card.body.addSpacing(4)

        # Maydonlar YONMA-YON emas, USTMA-UST. Ikki select bir qatorda
        # turganda ularning yorlig'i qisqarib ("Test turi" / "Test")
        # farqi yo'qoladi; zanjirli tanlovda esa aynan tartib muhim -
        # tepadagi pastdagini boshqaradi.
        card.body.addWidget(self._field_label("Test turi"))
        self.type_combo = QComboBox()
        self.type_combo.setStyleSheet(_COMBO_QSS)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        card.body.addWidget(self.type_combo)

        card.body.addSpacing(2)
        card.body.addWidget(self._field_label("Test"))
        self.exam_combo = QComboBox()
        self.exam_combo.setStyleSheet(_COMBO_QSS)
        self.exam_combo.currentIndexChanged.connect(self._on_exam_changed)
        card.body.addWidget(self.exam_combo)

        # TAYYORGARLIK: «Davom etish» nimaga bog'liqligi BIR QARASHDA.
        # Ilgari faqat o'chiq tugma va bitta xabar bor edi - operator
        # qolgan shartlar bajarilganmi, bilmasdi.
        card.body.addSpacing(8)
        card.body.addWidget(self._field_label("Tayyorgarlik"))
        self._readiness = {}
        for key, label in (
            ("computer", "Kompyuter"),
            ("camera", "Kamera tekshiruvi"),
            ("exam", "Test"),
        ):
            row = _ReadinessRow(label)
            self._readiness[key] = row
            card.body.addWidget(row)

        self.message = Notice(compact=True)
        card.body.addSpacing(4)
        card.body.addWidget(self.message)

        card.body.addStretch(1)

        self.continue_btn = RippleButton("DAVOM ETISH")
        self.continue_btn.setStyleSheet(primary_button_style(50))
        self.continue_btn.clicked.connect(self._on_continue)
        card.body.addWidget(self.continue_btn)
        return card

    def _render_readiness(self, *, has_exam: bool, is_open: bool) -> None:
        """
        Tayyorgarlik ro'yxati — `_update_continue_state` bilan BIR XIL
        shartlar (u qaror qiladi, bu faqat ko'rsatadi).
        """
        device = self._state.device
        if not self._has_computer:
            self._readiness["computer"].set_state("failed", "Bazada ro'yxatga olinmagan")
        elif not self._machine_ok:
            self._readiness["computer"].set_state("failed", "Tasdiqlanmadi")
        else:
            self._readiness["computer"].set_state(
                "ready", device.computer_label or device.inventory_code or "Tanildi"
            )

        result = self.camera_panel.check_result
        left = self._state.camera_check_left()
        if not result:
            required = policy_check.camera_check_required(self._state.config)
            self._readiness["camera"].set_state(
                "pending", "Tekshirilmagan" + ("" if required else " (ixtiyoriy)")
            )
        elif left is not None and left <= 0:
            self._readiness["camera"].set_state("warning", "Muddati tugagan — qayta tekshiring")
        elif not result.get("can_start", True):
            self._readiness["camera"].set_state("failed", "Tekshiruvdan o'tmadi")
        elif result.get("status") == "warning":
            self._readiness["camera"].set_state("warning", "O'tdi, ogohlantirishlar bilan")
        else:
            self._readiness["camera"].set_state("ready", "Tekshiruvdan o'tdi")

        exam = self.exam_combo.currentData()
        if not has_exam:
            self._readiness["exam"].set_state("pending", "Ochiq imtihon yo'q")
        elif not is_open:
            self._readiness["exam"].set_state("warning", "Kirish oynasi yopiq")
        else:
            self._readiness["exam"].set_state("ready", exam.name if exam else "Tanlandi")

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "field")
        return label

    # ------------------------------------------------------------------
    # Yangilash
    # ------------------------------------------------------------------
    def reload_all(self) -> None:
        """
        Handshake + kameralar - bitta amalda.

        Handshake kompyuter ma'lumotini, binoni, sozlamani va
        imtihonlar ro'yxatini birdan yangilaydi; kamera paneli esa
        biriktirishni va lokal qurilmalarni qayta o'qiydi. Operator
        uchun bu bitta savolning javobi: "hozir holat qanday?".
        """
        if self._reloading:
            return
        self._reloading = True
        self.header.set_reloading(True)
        self.message.show_message("Ma'lumotlar yangilanmoqda...", "info")

        # `refresh_machine=True` — MAC/IP keshdan emas, qaytadan
        # o'lchanadi va serverga yuboriladi. Aynan shu tugma
        # "mashina to'g'rimi?" degan savolni qayta so'raydi:
        # administrator kompyuterni endigina qo'shgan yoki operator
        # kabelni almashtirgan bo'lishi mumkin.
        worker = ApiWorker(self._auth.handshake, refresh_machine=True, parent=self)
        worker.succeeded.connect(self._on_reloaded)
        worker.failed.connect(self._on_reload_failed)
        self._workers.run(worker)

    def _on_reloaded(self, _device) -> None:
        self._reloading = False
        self.header.set_reloading(False)
        # MAC/IP qaytadan o'lchandi — sarlavhadagi qiymat ham
        # yangilanishi kerak (`refresh()` bo'sh keshni ko'rib
        # qayta so'raydi).
        self._identity = {}
        # `refresh()` kamera panelini ham qayta ishga soladi.
        self.refresh()
        # Modal AYNAN shu yerda: operator tugmani bosib javob
        # kutmoqda va inline xabar ekranning pastida ko'zdan
        # qochishi mumkin. Sahifa ochilganda esa modal chiqmaydi —
        # u yerda xabar bloki (`Notice`) va o'chirilgan tugma yetarli.
        self._warn_if_machine_blocked()

    def _on_reload_failed(self, message: str, code: str) -> None:
        self._reloading = False
        self.header.set_reloading(False)
        log.warning("Yangilash muvaffaqiyatsiz (%s): %s", code or "-", message)
        # Ekrandagi ma'lumot ESKI holida qoladi va bu to'g'ri: uni
        # tozalash operatorni ma'lumotsiz qoldirardi. Xabar esa
        # ma'lumot eskirgan bo'lishi mumkinligini aytadi.
        self.message.show_message(
            "{} Ekrandagi ma'lumot eskirgan bo'lishi mumkin.".format(message),
            "error",
            title="Ma'lumotlar yangilanmadi",
        )

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Handshake'dan keyin chaqiriladi - ro'yxatlarni to'ldiradi."""
        device = self._state.device

        self.header.set_subtitle("Kameralarni tekshiring va testni tanlang")
        self._render_context()
        if not self._identity:
            self._resolve_identity()

        # Kamera paneli handshake ro'yxatini oladi: unda shu ish
        # o'rnini kuzatadigan IP kameralar bor (kredensialsiz).
        self.camera_panel.refresh(handshake_cameras=device.cameras)

        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        types = self._state.exam_types()
        if not types:
            self.type_combo.addItem("Bugun uchun imtihon yo'q", None)
            self.type_combo.setEnabled(False)
            self.exam_combo.setEnabled(False)
        else:
            self.type_combo.setEnabled(True)
            self.exam_combo.setEnabled(True)
            for type_id, type_name in types:
                self.type_combo.addItem(type_name, type_id)
        self.type_combo.blockSignals(False)
        self._on_type_changed()

    def _render_context(self) -> None:
        staff = self._state.staff
        device = self._state.device
        tooltips, captions = ip_chip_hints(self._identity.get("ips"))
        # KOMPYUTER RAQAMI o'ngdagi yirik nishonda (`SeatBadge`): raqam
        # bo'lmasa inventar kodi, kompyuter umuman biriktirilmagan
        # bo'lsa nishon yashiriladi. To'liq nom ("№12 · PC-0012")
        # tooltip'da.
        self.header.set_seat(device)
        self.header.set_context(
            region=staff.region_name if staff else "",
            zone=device.zone_name or ("aniqlanmadi" if not self._has_computer else ""),
            mac=self._identity.get("mac", ""),
            # ASOSIY manzil - marshrut tanlagani. Mashinada bir
            # nechta manzil bo'lsa qolganlari tooltip'da.
            ip=self._identity.get("ip", ""),
            # MAC nomuvofiqligi ham chiplarni QIZIL qiladi: aynan
            # o'sha yerda MAC qiymati turibdi va operator sababni
            # o'sha qiymatdan boshlab qidiradi.
            ok=self._has_computer and self._machine_ok,
            tooltips=tooltips,
            captions=captions,
        )

    @property
    def _machine_ok(self) -> bool:
        """
        Server mashinani tanidimi (MAC ro'yxatda bormi).

        QAROR SERVERNIKI. Client MAC ni faqat o'lchaydi va
        yuboradi; "ruxsat bormi" degan javob handshake'dan keladi
        (`REQUIRE_MAC_MATCH` sozlamasi ham o'sha yerda hisobga
        olingan). Client tomonda qayta hisoblash ikkita qoidani
        yaratardi va ular albatta ajralib ketardi.
        """
        return self._state.device.machine_allowed

    def _warn_if_machine_blocked(self) -> None:
        """Yangilashdan keyin — modal ogohlantirish."""
        if self._machine_ok:
            return
        device = self._state.device
        # MD3 dialog (`QMessageBox` emas - tizim oynasi kiosk uslubidan
        # chiqib turardi va CLAUDE.md qoidasi).
        if self._machine_dialog is None:
            from ui.dialogs.notice_dialog import NoticeDialog

            self._machine_dialog = NoticeDialog(self.window())
        self._machine_dialog.show_notice(
            "Mashina tanilmadi",
            "{}\n\nBu kompyuterda imtihonni boshlab bo'lmaydi.".format(
                device.machine_message
                or "Bu mashina bazadagi ro'yxat bilan mos kelmadi."
            ),
            kind="error",
        )

    def _resolve_identity(self) -> None:
        """MAC va IP - fon rejimida, bir marta."""
        worker = ApiWorker(_machine_identity, parent=self)
        worker.succeeded.connect(self._on_identity)
        # Xato holatida sarlavhada chiziqcha qoladi: bu ma'lumot
        # diagnostika uchun va uning yo'qligi oqimni to'xtatmaydi.
        worker.failed.connect(
            lambda message, code: log.info("Mashina ma'lumoti olinmadi: %s", message)
        )
        self._workers.run(worker)

    def _on_identity(self, result) -> None:
        self._identity = result or {}
        self._render_context()

    @property
    def _has_computer(self) -> bool:
        """
        Bu mashina bazada ro'yxatga olinganmi.

        `inventory_code` handshake javobidagi `computer` blokidan
        keladi va u BO'SH bo'lishi mumkin: server `device_id` ni
        biladi, lekin unga kompyuter biriktirilmagan. Bu holat
        oqimning davomini MA'NOSIZ qiladi - sessiyaning binosi
        bo'lmaydi, ya'ni `candidate/lookup/` jadval tekshiruvidan
        o'tolmaydi va dashboard sessiyani hech qaysi binoda
        ko'rsatmaydi.
        """
        return bool(self._state.device.inventory_code)

    def _on_cameras_resolved(self, layout) -> None:
        """
        Aniqlangan taqsimot `AppState` ga yoziladi.

        Keyingi sahifalar undan foydalanadi: FaceID birlamchi
        kamerani oladi, obyekt aniqlash esa ikkilamchisini. Ular
        qaytadan aniqlashi mumkin emas - qurilmani ikki marta
        sanash sekin va natija farq qilishi mumkin.
        """
        self._state.cameras = layout

    # ------------------------------------------------------------------
    def stop_preview(self) -> None:
        """
        Kamerani bo'shatadi - sahifadan chiqishdan OLDIN.

        FaceID sahifasi o'sha veb-kamerani ochadi va Windows'da band
        qurilma umuman ochilmaydi.
        """
        self.camera_panel.stop_preview()

    def shutdown(self) -> None:
        self.camera_panel.shutdown()
        self._workers.wait_all(5000)

    # ------------------------------------------------------------------
    def _on_type_changed(self) -> None:
        type_id = self.type_combo.currentData()
        self.exam_combo.blockSignals(True)
        self.exam_combo.clear()
        exams = self._state.exams_of_type(type_id)
        for exam in exams:
            # Yopiq imtihon ham ko'rsatiladi, lekin tanlab bo'lmaydi -
            # operator "nega ro'yxatda yo'q" deb qidirmasligi uchun.
            suffix = "" if exam.is_open else "  (kirish oynasi yopiq)"
            self.exam_combo.addItem(exam.name + suffix, exam)
        self.exam_combo.blockSignals(False)
        self._on_exam_changed()

    def _on_exam_changed(self) -> None:
        # Tekshiruv TANLANGAN imtihon siyosati bo'yicha baholanadi:
        # bitta mashinada bitta kamera SAT uchun yetmasligi va mashq
        # testi uchun yetishi mumkin.
        exam = self.exam_combo.currentData()
        self.camera_panel.set_exam(exam.id if exam is not None else None)
        self._update_continue_state()

    def _on_check_completed(self, result) -> None:
        """Tekshiruv natijasi 'Davom etish' xabarida ham aks etadi."""
        # Bo'sh natija (tekshiruv yiqildi, rollar almashdi) serverdagi
        # suratchaga TEGMAYDI - u o'z muddati bilan yashayveradi.
        if result:
            self._state.note_camera_check(result)
        self._update_continue_state()

    def preselect_exam(self, exam_id: int) -> bool:
        """
        Imtihonni ro'yxatdan oldindan tanlaydi (kutilmagan yopilishdan
        keyingi tiklash - `MainWindow._offer_resume`). `False` - bugungi
        ro'yxatda yo'q (operator o'zi tanlaydi).
        """
        for type_index in range(self.type_combo.count()):
            type_id = self.type_combo.itemData(type_index)
            exams = self._state.exams_of_type(type_id)
            if not any(exam.id == exam_id for exam in exams):
                continue
            self.type_combo.setCurrentIndex(type_index)
            for exam_index in range(self.exam_combo.count()):
                exam = self.exam_combo.itemData(exam_index)
                if exam is not None and exam.id == exam_id:
                    self.exam_combo.setCurrentIndex(exam_index)
                    return True
        return False

    def _update_continue_state(self) -> None:
        """
        "Davom etish" faolligi UCHTA shartga bog'liq.

        Ular bitta joyda hisoblanadi, chunki har biri boshqa paytda
        o'zgaradi (yangilash, tur tanlash, imtihon tanlash) va uchta
        joyda alohida `setEnabled` yozilsa, oxirgi ishga tushgani
        boshqalarning qarorini bekor qilardi.

        Xabar ham SHU YERDA: eng jiddiy to'siq ko'rsatiladi. Ikkita
        ogohlantirishni birga chiqarish operatorni qaysi birini
        avval hal qilishni tanlashga majbur qilardi.
        """
        exam = self.exam_combo.currentData()
        has_exam = bool(self._state.exams) and exam is not None
        is_open = bool(exam and exam.is_open)

        allowed = self._has_computer and self._machine_ok and has_exam and is_open
        # Tekshiruv ketayotgan bo'lsa tugmaga TEGILMAYDI: operator
        # combo'ni o'zgartirsa, bu metod ishga tushadi va bloklangan
        # tugmani qaytadan yoqib yuborardi - natijada ikkita parallel
        # `exam/config/` so'rovi ketardi.
        if self._pending_exam is None:
            self.continue_btn.setEnabled(bool(allowed))
        self._render_readiness(has_exam=has_exam, is_open=is_open)

        if not self._has_computer:
            self.message.show_message(
                "Imtihonni boshlab bo'lmaydi. Administrator uni MAC manzili "
                "bilan qo'shishi kerak.",
                "error",
                title="Kompyuter bazada ro'yxatga olinmagan",
            )
        elif not self._machine_ok:
            # Matn SERVERDAN: u qaysi bino qidirilganini va qaysi
            # kompyuter kutilganini biladi. Client tomonda umumiy
            # matn yozish operatorni "nima qilay?" degan savol bilan
            # qoldirardi.
            self.message.show_message(
                self._state.device.machine_message
                or "Bu mashinaning MAC manzili bazadagi ro'yxatda topilmadi.",
                "error",
                title="Kompyuter tasdiqlanmadi",
            )
        elif not has_exam:
            self.message.show_message(
                "Bugungi sanaga imtihon jadvali tuzilmagan yoki barcha "
                "imtihonlar yopiq.",
                "warning",
                title="Ochiq imtihon yo'q",
            )
        elif not is_open:
            self.message.show_message(
                "Bu imtihonning kirish oynasi hozir yopiq.", "warning"
            )
        else:
            self.message.clear_message()

    def _on_continue(self) -> None:
        """
        Tanlangan imtihonning profilini joriy qiladi va tekshiradi.

        Ketma-ketlik ataylab shunday:

            1. mahalliy to'siqlar (kompyuter, imtihon tanlangan va
               ochiq) - ular serverga so'rov yubormasdan hal bo'ladi;
            2. imtihon profilini YUKLASH (`exam/config/`);
            3. profil bilan ish o'rnini SOLISHTIRISH;
            4. natijaga qarab: jimgina o'tish, ogohlantirish yoki
               to'siq.

        Ikkinchi qadam KECHIKTIRILGAN va bu ongli: profil imtihon
        tanlangandan keyingina ma'lum bo'ladi, uni har bir combo
        o'zgarishida yuklash esa operator ro'yxatni varaqlab
        ko'rayotganda o'nlab bekorga so'rov yuborardi.
        """
        # Tugma allaqachon bloklangan bo'ladi, lekin tekshiruv
        # TAKRORLANADI: `setEnabled` UI holati va u signal tartibi
        # o'zgarganda (masalan yangilash o'rtasida bosilsa) eskirgan
        # bo'lishi mumkin. Oqimni to'sadigan qaror ko'rinishga
        # tayanmasligi kerak.
        if not self._has_computer:
            self.message.show_message(
                "Bu kompyuter bazada ro'yxatga olinmagan — davom etib bo'lmaydi.",
                "error",
            )
            return

        if not self._machine_ok:
            # Takroriy tekshiruv `_has_computer` dagi bilan bir
            # sababdan: `setEnabled` UI holati va u signal tartibi
            # o'zgarganda eskirgan bo'lishi mumkin.
            self.message.show_message(
                self._state.device.machine_message
                or "Bu mashinaning MAC manzili bazadagi ro'yxatda topilmadi.",
                "error",
                title="Kompyuter tasdiqlanmadi",
            )
            self._warn_if_machine_blocked()
            return

        exam: ExamOption = self.exam_combo.currentData()
        if exam is None:
            self.message.show_message("Testni tanlang", "warning")
            return
        if not exam.is_open:
            self.message.show_message(
                "Bu imtihonning kirish oynasi hozir yopiq.", "warning"
            )
            return

        self._pending_exam = exam
        self._set_checking(True)
        worker = ApiWorker(self._repo.exam_config, exam_id=exam.id, parent=self)
        worker.succeeded.connect(self._on_exam_config)
        worker.failed.connect(self._on_exam_config_failed)
        self._workers.run(worker)

    def _set_checking(self, busy: bool) -> None:
        self.continue_btn.setEnabled(not busy)
        self.continue_btn.setText("TEKSHIRILMOQDA..." if busy else "DAVOM ETISH")

    def _on_exam_config(self, payload) -> None:
        payload = payload or {}
        config = payload.get("config") or {}
        setting = payload.get("setting") or {}

        # PROFIL SHU YERDA JORIY QILINADI. Handshake bergan global
        # profil almashtiriladi: bundan keyingi barcha sahifalar
        # (FaceID chegarasi, skrinshot oralig'i, WebView siyosati)
        # aynan shu imtihonning qiymatlarini o'qiydi.
        self._state.config = config
        log.info(
            "Imtihon profili joriy qilindi: %s (sozlama: %s%s)",
            (payload.get("exam") or {}).get("name") or "-",
            setting.get("name") or "-",
            "" if setting.get("is_exam_specific") else ", global standart",
        )
        self._rescan_threats(
            config=config,
            setting_name=self._setting_caption(setting),
            loaded=True,
        )

    def _on_exam_config_failed(self, message: str, code: str) -> None:
        # Profil olinmadi - global profil kuchda qoladi. Bu
        # ogohlantirish, to'siq emas; sabab `proctoring/policy.py`
        # dagi izohda.
        log.warning("Imtihon profilini olib bo'lmadi (%s): %s", code or "-", message)
        self._rescan_threats(config={}, setting_name="", loaded=False)

    # ------------------------------------------------------------------
    def _rescan_threats(self, *, config: dict, setting_name: str, loaded: bool) -> None:
        """
        Tozalashni QAYTADAN bajaradi — "Davom etish" bosilgan paytda.

        NIMA UCHUN ISHGA TUSHISHDAGI HISOBOT YETARLI EMAS. Dastur
        ochilgandan keyin imtihon boshlanishigacha bir necha daqiqa,
        ba'zan soatlar o'tadi: operator kirgan, talabgorlar navbatda
        turgan. Shu oraliqda AnyDesk qayta ishga tushirilgan bo'lishi
        mumkin — eski hisobotga tayanish esa "tekshirildi" degan
        yolg'on xabar bo'lardi.

        Teskari holat ham xuddi shunday muhim: operator masofaviy
        boshqaruv dasturini KO'RSATILGANIDEK o'chirgan bo'lishi
        mumkin. Eski hisobot bilan imtihon baribir to'silib turardi
        va uni ochishning yagona yo'li dasturni qayta ishga tushirish
        bo'lardi.

        FON THREAD'IDA: skanerlash ~0.3-2 soniya (imzolarni o'qish,
        xizmatlar ro'yxati) va UI thread'da u oynani muzlatardi.

        Shu chaqiruvda ULANGAN TASHQI XOTIRA ham tekshiriladi
        (`_scan_machine`), panelda «Qo'shimcha qurilmalar» yoqilgan
        bo'lsa. Skaner ham, qurilmalar ham o'chiq bo'lsa qadam butunlay
        o'tkazib yuboriladi — `_finish_check` `None` hisobot bilan
        chaqiriladi.
        """
        from config import (
            THREAT_ALLOW_VIRTUAL_HOST,
            THREAT_SCAN_ALLOW,
            THREAT_SCAN_ENABLED,
        )

        # TASHQI XOTIRA ham shu yerda (ishga tushishdan oldin ulangani
        # ham): operator uni talabgor kelishidan oldin ko'radi.
        detect_peripherals = self._detect_peripherals(config)
        if not THREAT_SCAN_ENABLED and not detect_peripherals:
            self._finish_check(
                config=config, setting_name=setting_name, loaded=loaded, threats=None
            )
            return

        from services import threat_scanner

        def fallback_threats():
            # Skaner yiqildi. OXIRGI MA'LUM hisobotga qaytamiz: uni
            # butunlay tashlab yuborish ishga tushishda topilgan
            # tahdidni jimgina kechirardi.
            return threat_scanner.last_report() if THREAT_SCAN_ENABLED else None

        def done(result) -> None:
            result = result or {}
            threats = None
            if THREAT_SCAN_ENABLED:
                if result.get("threat_error"):
                    threats = fallback_threats()
                else:
                    threats = result.get("threats")
                    threat_scanner.remember(threats)
            self._finish_check(
                config=config, setting_name=setting_name, loaded=loaded,
                threats=threats, peripherals=result.get("peripherals"),
            )

        def failed(message: str, code: str) -> None:
            log.warning("Mashina tekshiruvi ishlamadi (%s): %s", code or "-", message)
            self._finish_check(
                config=config,
                setting_name=setting_name,
                loaded=loaded,
                threats=fallback_threats(),
            )

        worker = ApiWorker(
            _scan_machine,
            threats=THREAT_SCAN_ENABLED,
            peripherals=detect_peripherals,
            allow=THREAT_SCAN_ALLOW,
            allow_virtual_host=THREAT_ALLOW_VIRTUAL_HOST,
            parent=self,
        )
        worker.succeeded.connect(done)
        worker.failed.connect(failed)
        self._workers.run(worker)

    def _detect_peripherals(self, config: dict) -> bool:
        """
        Panelda «Qo'shimcha qurilmalar» yoqilganmi (`device.detect_peripherals`).

        Imtihon profili olinmagan bo'lsa (`config={}`) - handshake'dagi
        global profil: imtihon ham baribir shu bilan boshlanadi.
        """
        source = config or self._state.config or {}
        return bool((source.get("device") or {}).get("detect_peripherals", False))

    @staticmethod
    def _setting_caption(setting: dict) -> str:
        name = setting.get("name") or ""
        if not name:
            return ""
        return "{} profili{}".format(
            name, "" if setting.get("is_exam_specific") else " (global standart)"
        )

    def _finish_check(
        self, *, config: dict, setting_name: str, loaded: bool, threats=None,
        peripherals=None,
    ) -> None:
        self._set_checking(False)
        exam = self._pending_exam
        self._pending_exam = None
        if exam is None:
            return

        from services import runtime_settings
        from services.face_engine import FaceEngine

        check_result = self.camera_panel.check_result
        # Natija ekranda qolgan, lekin serverda muddati o'tgan (operator
        # sahifada soatlab turdi) - u yo'q deb hisoblanadi, aks holda
        # to'siq yana faqat `proctoring/start/` da chiqardi.
        left = self._state.camera_check_left()
        check_expired = bool(check_result) and left is not None and left <= 0
        issues = policy_check.check_readiness(
            config=config,
            layout=self._state.cameras,
            face_ready=FaceEngine().is_ready,
            config_loaded=loaded,
            # Server tekshiruvi mavjud bo'lsa, kamera bo'yicha xulosa
            # AYNAN undan olinadi - u haqiqiy o'lchovlarni ko'rgan.
            check_result={} if check_expired else check_result,
            check_expired=check_expired,
            threats=threats,
            # IMTIHON SIYOSATI (`rdp.block_exam`, panelda "Yo'q qilinmagan
            # tahdid imtihonni to'sadi"). Profil kelmagan bo'lsa
            # (`config={}`) - `.env` dagi `THREAT_BLOCK_EXAM` zaxirasi.
            threats_block=runtime_settings.get(config, "rdp.block_exam"),
            # Fleshka, tashqi disk, telefon - ogohlantirish (to'siq emas).
            peripherals=peripherals,
        )

        if not issues:
            # Muammo yo'q - operatorni bekorga to'xtatmaymiz.
            self._proceed(exam)
            return

        dialog = PolicyDialog(
            self.window(),
            exam_name=exam.name,
            setting_name=setting_name,
            issues=issues,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted

        if dialog.has_blocking:
            # To'siq bor - dialog "davom etish" ni umuman taklif
            # qilmaydi va bu yerda ham hech narsa qilinmaydi.
            log.warning(
                "Imtihon boshlanmadi (%s): %s",
                exam.name,
                "; ".join(item.title for item in policy_check.blocking(issues)),
            )
            self.message.show_message(
                "Sozlama talablariga mos kelmadi — yuqoridagi sabablarni bartaraf "
                "eting va qaytadan urinib ko'ring.",
                "error",
                title="Imtihon boshlanmadi",
            )
            return

        if accepted:
            log.info(
                "Operator ogohlantirishlarni tasdiqladi (%s): %s",
                exam.name,
                "; ".join(item.title for item in issues),
            )
            self._proceed(exam)

    def _proceed(self, exam: ExamOption) -> None:
        self._state.selected_exam = exam
        self.exam_selected.emit(exam)
