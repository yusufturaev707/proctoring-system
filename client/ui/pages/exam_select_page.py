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
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from proctoring import policy as policy_check
from services import system_info
from services.app_state import AppState, ExamOption
from services.workers import ApiWorker, WorkerHolder
from ui.dialogs.policy_dialog import PolicyDialog
from ui.styles import primary_button_style
from ui.widgets.camera_panel import CameraPanel
from ui.widgets.header import WorkstationHeader, ip_chip_hints
from ui.widgets.indicators import Card, MessageBar

log = logging.getLogger(__name__)

#: "Davom etish" tugmasining kengligi.
#:
#: To'liq kenglikdagi tugma kartaning butun pastki chetini egallab,
#: sahifadagi eng og'ir elementga aylanardi - holbuki u oddiy
#: navigatsiya qadami. Ixcham va markazlashtirilgan tugma o'z
#: og'irligiga qaytadi.
_CONTINUE_WIDTH = 280


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
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(48, 28, 48, 32)
        root.setSpacing(20)

        self.header = WorkstationHeader()
        self.header.reload_requested.connect(self.reload_all)
        root.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(20)

        # --- Chap: kameralar (kengroq ustun) ---
        # `show_reload=False` - yangilash sarlavhada, bitta umumiy
        # ikonkada.
        self.camera_panel = CameraPanel(self._repo, show_reload=False)
        self.camera_panel.layout_resolved.connect(self._on_cameras_resolved)
        self.camera_panel.check_completed.connect(self._on_check_completed)
        body.addWidget(self.camera_panel, 3)

        # --- O'ng: tanlov ---
        body.addWidget(self._build_form_card(), 2)

        root.addLayout(body)

    def _build_form_card(self) -> Card:
        card = Card("Test ma'lumotlari")

        # Maydonlar YONMA-YON emas, USTMA-UST. Ikki select bir qatorda
        # turganda ularning yorlig'i qisqarib ("Test turi" / "Test")
        # farqi yo'qoladi; zanjirli tanlovda esa aynan tartib muhim -
        # tepadagi pastdagini boshqaradi.
        card.body.addWidget(self._field_label("Test turi"))
        self.type_combo = QComboBox()
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        card.body.addWidget(self.type_combo)

        card.body.addSpacing(8)
        card.body.addWidget(self._field_label("Test"))
        self.exam_combo = QComboBox()
        self.exam_combo.currentIndexChanged.connect(self._on_exam_changed)
        card.body.addWidget(self.exam_combo)

        self.message = MessageBar()
        card.body.addSpacing(6)
        card.body.addWidget(self.message)

        # Tugma qolgan bo'shliqning MARKAZIDA: tepada va pastda teng
        # cho'zilma. Pastga mahkamlangan to'liq kenglikdagi tugma
        # kartaning butun chetini egallab, oddiy navigatsiya qadamini
        # sahifadagi eng og'ir elementga aylantirardi.
        card.body.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.continue_btn = QPushButton("DAVOM ETISH")
        self.continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.continue_btn.setStyleSheet(primary_button_style(50))
        self.continue_btn.setFixedWidth(_CONTINUE_WIDTH)
        self.continue_btn.clicked.connect(self._on_continue)
        button_row.addWidget(self.continue_btn)
        button_row.addStretch(1)
        card.body.addLayout(button_row)

        card.body.addStretch(1)
        return card

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
        # u yerda `MessageBar` va o'chirilgan tugma yetarli.
        self._warn_if_machine_blocked()

    def _on_reload_failed(self, message: str, code: str) -> None:
        self._reloading = False
        self.header.set_reloading(False)
        log.warning("Yangilash muvaffaqiyatsiz (%s): %s", code or "-", message)
        # Ekrandagi ma'lumot ESKI holida qoladi va bu to'g'ri: uni
        # tozalash operatorni ma'lumotsiz qoldirardi. Xabar esa
        # ma'lumot eskirgan bo'lishi mumkinligini aytadi.
        self.message.show_message(
            "{} Ekrandagi ma'lumot eskirgan bo'lishi mumkin.".format(message), "error"
        )

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Handshake'dan keyin chaqiriladi - ro'yxatlarni to'ldiradi."""
        staff = self._state.staff
        device = self._state.device

        self.header.set_staff(
            staff.full_name if staff else "",
            "1-qadam · Imtihonni tanlang",
        )
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
        QMessageBox.warning(
            self.window(),
            "Mashina tanilmadi",
            "{}\n\nBu kompyuterda imtihonni boshlab bo'lmaydi.".format(
                device.machine_message
                or "Bu mashina bazadagi ro'yxat bilan mos kelmadi."
            ),
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

    def _on_check_completed(self, _result) -> None:
        """Tekshiruv natijasi 'Davom etish' xabarida ham aks etadi."""
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

        if not self._has_computer:
            self.message.show_message(
                "Bu kompyuter bazada ro'yxatga olinmagan — imtihonni boshlab "
                "bo'lmaydi. Administrator uni MAC manzili bilan qo'shishi kerak.",
                "error",
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
            )
        elif not has_exam:
            self.message.show_message(
                "Bugungi sanaga imtihon jadvali tuzilmagan yoki barcha "
                "imtihonlar yopiq.",
                "warning",
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
            )
            self._warn_if_machine_blocked()
            return

        exam: ExamOption = self.exam_combo.currentData()
        if exam is None:
            self.message.show_message("Testni tanlang")
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

        Skaner o'chirilgan bo'lsa qadam butunlay o'tkazib yuboriladi —
        `_finish_check` `None` hisobot bilan chaqiriladi va tahdid
        bo'yicha hech qanday muammo qo'shilmaydi.
        """
        from config import (
            THREAT_ALLOW_VIRTUAL_HOST,
            THREAT_SCAN_ALLOW,
            THREAT_SCAN_ENABLED,
        )

        if not THREAT_SCAN_ENABLED:
            self._finish_check(
                config=config, setting_name=setting_name, loaded=loaded, threats=None
            )
            return

        from services import threat_scanner

        def done(report) -> None:
            threat_scanner.remember(report)
            self._finish_check(
                config=config, setting_name=setting_name, loaded=loaded, threats=report
            )

        def failed(message: str, code: str) -> None:
            # Skaner yiqildi. OXIRGI MA'LUM hisobotga qaytamiz: uni
            # butunlay tashlab yuborish ishga tushishda topilgan
            # tahdidni jimgina kechirardi.
            log.warning("Tahdid skaneri qayta ishlamadi (%s): %s", code or "-", message)
            self._finish_check(
                config=config,
                setting_name=setting_name,
                loaded=loaded,
                threats=threat_scanner.last_report(),
            )

        worker = ApiWorker(
            threat_scanner.sweep,
            allow=THREAT_SCAN_ALLOW,
            allow_virtual_host=THREAT_ALLOW_VIRTUAL_HOST,
            parent=self,
        )
        worker.succeeded.connect(done)
        worker.failed.connect(failed)
        self._workers.run(worker)

    @staticmethod
    def _setting_caption(setting: dict) -> str:
        name = setting.get("name") or ""
        if not name:
            return ""
        return "{} profili{}".format(
            name, "" if setting.get("is_exam_specific") else " (global standart)"
        )

    def _finish_check(
        self, *, config: dict, setting_name: str, loaded: bool, threats=None
    ) -> None:
        self._set_checking(False)
        exam = self._pending_exam
        self._pending_exam = None
        if exam is None:
            return

        from services import runtime_settings
        from services.face_engine import FaceEngine

        issues = policy_check.check_readiness(
            config=config,
            layout=self._state.cameras,
            face_ready=FaceEngine().is_ready,
            config_loaded=loaded,
            # Server tekshiruvi mavjud bo'lsa, kamera bo'yicha xulosa
            # AYNAN undan olinadi - u haqiqiy o'lchovlarni ko'rgan.
            check_result=self.camera_panel.check_result,
            threats=threats,
            # IMTIHON SIYOSATI (`rdp.block_exam`, panelda "Yo'q qilinmagan
            # tahdid imtihonni to'sadi"). Profil kelmagan bo'lsa
            # (`config={}`) - `.env` dagi `THREAT_BLOCK_EXAM` zaxirasi.
            threats_block=runtime_settings.get(config, "rdp.block_exam"),
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
