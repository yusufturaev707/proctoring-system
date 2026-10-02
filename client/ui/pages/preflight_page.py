"""
0-SAHIFA - tarmoq tekshiruvi (preflight).

Login formasidan OLDIN turadi va uni to'sadi. Sabab oqim mantig'ida:
IP cheklovi baribir har bir client so'rovida tekshiriladi, lekin agar
to'siq faqat o'sha yerda ko'rinsa, operator login/parol kiritib,
imtihonni tanlab, JSHSHIR yozib, faqat shundan keyin "bu IP manzildan
kirishga ruxsat yo'q" degan javobni olardi. Xato oqimning eng boshida
ko'rinishi kerak - shunda operator nima qilishini darhol biladi.

To'rtta to'xtash holati bor va ular ATAYLAB ajratilgan, chunki
operatorning harakati har birida boshqacha:

    ip_not_allowed      - manzil ma'lum, ro'yxatda yo'q -> administrator
                          uni panelga qo'shishi kerak;
    ip_allowlist_empty  - ro'yxat umuman to'ldirilmagan -> sabab
                          operatorda emas, sozlamada;
    public_ip_unknown   - internet yo'q -> tarmoq kabelini/Wi-Fi ni
                          tekshirish;
    tarmoq xatosi       - server bilan aloqa yo'q -> serverni yoki LAN
                          ulanishini tekshirish.

DIZAYN. Karta Material Design 3 dialog naqshiga quriladi va uning
tuzilishi har bir holatda BIR XIL qoladi - faqat mazmun almashadi:

    wordmark -> nishon -> sarlavha -> chaqiriq -> ma'lumot bloki ->
    xabar -> amallar

Tartib o'zgarmasligi muhim: operator kuniga o'nlab marta shu ekranni
ko'radi va nigohi qayerga tushishini o'rganib qoladi. Tashqi IP alohida
blokda va moslashuvchan (monospace) shriftda - uni ADMINISTRATORGA
o'qib berish kerak, ya'ni 5 va S, 0 va O farqlanishi shart.

Sahifa O'ZI hech narsani hal qilmaydi: qaror serverda, bu yerda faqat
uni ko'rsatish va qayta urinish imkoni.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import APP_VERSION
from services import system_info
from services.repositories import DeviceRepository
from services.workers import ApiWorker, WorkerHolder
from ui.styles import COLORS, info_field_style, outlined_button_style
from ui.widgets.backdrop import BrandBackdrop
from ui.widgets.indicators import MessageBar, StateBadge

log = logging.getLogger(__name__)

#: Ruxsat berilgandan keyin login sahifasiga o'tishdan oldingi pauza.
#: Nolga teng bo'lsa, operator qaysi bino sifatida tanilganini
#: umuman ko'rmay qoladi - ekran bir zumda almashadi.
_HANDOFF_DELAY_MS = 900

#: Karta kengligi: oyna kengligining ulushi, shu chegaralar ichida.
#: Qat'iy piksel emas - dastur 1366x768 dan 4K gacha ekranlarda
#: ishlaydi va 520 px kichik ekranda deyarli butun oynani egallardi,
#: kattasida esa yo'qolib ketardi.
_CARD_MIN_WIDTH = 380
_CARD_MAX_WIDTH = 520
_CARD_WIDTH_RATIO = 0.42

#: Raqamlar uchun - 5/S va 0/O farqlanishi shart.
_MONO_FAMILIES = ["Cascadia Mono", "Consolas", "SF Mono", "Courier New"]


def _apply_font(widget, size: int, *, bold: bool = False,
                families: list | None = None, extra: str = "") -> None:
    """
    Shriftni IKKI joyda beradi va ikkalasi ham kerak.

    `setStyleSheet` - chizish uchun: `GLOBAL_STYLESHEET` da
    `QWidget { font-size: 15px }` qoidasi bor va Qt'da uslub har doim
    `setFont` dan ustun turadi, ya'ni faqat `setFont` bilan matn 15 px
    bo'lib qolaveradi.

    `setFont` - o'lcham uchun: uslubdagi `font-size` widget'ning
    `sizeHint` iga har doim ham yetib bormaydi va matn o'z maydoniga
    sig'may pastdan kesiladi. Kichik ekranda bu aynan IP raqamida
    ko'rindi - operator uchun eng muhim qatorda.
    """
    font = QFont()
    font.setFamilies(families or ["Segoe UI", "Inter", "Roboto"])
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    widget.setFont(font)

    family = ", ".join("'{}'".format(name) for name in families) if families else ""
    widget.setStyleSheet(
        "font-size: {}px; font-weight: {};{} background: transparent; {}".format(
            size,
            700 if bold else 400,
            " font-family: {};".format(family) if family else "",
            extra,
        )
    )
    # Kamida BITTA qator sig'sin. Layout tor bo'lganda Qt yorliqni
    # `minimumSizeHint` gacha siqadi va u shrift balandligidan kichik
    # bo'lishi mumkin - natijada matnning pastki qismi kesiladi.
    # O'ralib ketadigan matnlar bundan ziyon ko'rmaydi: bu pol,
    # shift emas.
    widget.setMinimumHeight(QFontMetrics(font).height() + 2)

_CHECKING_TITLE = "Tarmoq tekshirilmoqda"
_CHECKING_TEXT = (
    "Kompyuter ro'yxatga olingan imtihon markazidan ulanayotgani tekshirilmoqda."
)


class PreflightPage(BrandBackdrop):
    """Tarmoq ruxsatini tekshiradi va faqat o'tgandagina yo'l ochadi."""

    #: (natija) - tekshiruv muvaffaqiyatli, login sahifasiga o'tish mumkin.
    passed = pyqtSignal(object)
    exit_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._repo = DeviceRepository()
        self._workers = WorkerHolder()
        self._busy = False
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch()

        # Login sahifasidagi bilan AYNAN bir xil joyda (`make_logo`).
        outer.addWidget(self.make_logo(), alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addSpacing(26)

        card = QFrame()
        card.setObjectName("preflightCard")
        # MD3 shape scale: "extra large" (28 px) - dialog darajasidagi
        # element uchun standart burchak radiusi.
        card.setStyleSheet(
            """
            QFrame#preflightCard {
                background-color: %s;
                border-radius: 28px;
                border: none;
            }
            """
            % COLORS["surface_container_lowest"]
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(64)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 140))
        card.setGraphicsEffect(shadow)
        self._card = card

        layout = QVBoxLayout(card)
        layout.setContentsMargins(34, 28, 34, 24)
        layout.setSpacing(0)

        # --- 1. Wordmark: HAR QANDAY holatda joyida qoladi -------------
        # To'siq ekrani ham dasturning O'Z ekrani ekani ko'rinib turishi
        # kerak - aks holda u "tizim xatosi" kabi o'qiladi va operator
        # nima ishlamayotganini tushunmaydi.
        mark = QLabel("PROCTORING")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _apply_font(mark, 12, bold=True,
                    extra="color: {}; letter-spacing: 3px;".format(COLORS["primary"]))
        layout.addWidget(mark)
        layout.addSpacing(20)

        # --- 2. Holat nishoni (MD3 tonal konteyner) -------------------
        badge_row = QHBoxLayout()
        badge_row.addStretch()
        self._badge = StateBadge(size=76)
        badge_row.addWidget(self._badge)
        badge_row.addStretch()
        layout.addLayout(badge_row)
        layout.addSpacing(16)

        # --- 3. Sarlavha (MD3 headline-small) -------------------------
        self._title = QLabel()
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        _apply_font(self._title, 22, bold=True,
                    extra="color: {};".format(COLORS["text"]))
        layout.addWidget(self._title)
        layout.addSpacing(6)

        # --- 4. Chaqiriq / yordamchi matn (MD3 body) ------------------
        self._subtitle = QLabel()
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        layout.addWidget(self._subtitle)

        # --- 5..7 Pastki blok: ma'lumot, xabar, amallar ---------------
        #
        # Uchalasi BITTA konteynerda va oraliqlar shu konteynerning
        # `spacing` i orqali beriladi. `layout.addSpacing()` bilan
        # qilinsa, bo'shliq yashirilgan widget'dan keyin ham qolib
        # ketardi: "tekshirilmoqda" holatida kartaning pastida sababsiz
        # bo'sh joy ko'rinardi. Qt esa yashirin widget'ni layoutdan
        # butunlay chiqarib tashlaydi - oraliq bilan birga.
        self._details = QWidget()
        self._details.setStyleSheet("background: transparent;")
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(0, 16, 0, 0)
        details_layout.setSpacing(12)
        layout.addWidget(self._details)

        self._info = QFrame()
        self._info.setObjectName("infoField")
        self._info.setStyleSheet(info_field_style())
        info_layout = QVBoxLayout(self._info)
        info_layout.setContentsMargins(16, 11, 16, 12)
        info_layout.setSpacing(1)

        self._info_label = QLabel("CHIQUVCHI IP MANZIL")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _apply_font(self._info_label, 11, bold=True,
                    extra="color: {}; letter-spacing: 1px;".format(COLORS["text_muted"]))
        info_layout.addWidget(self._info_label)

        self._info_value = QLabel("—")
        self._info_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Operator bu raqamni administratorga aytadi yoki nusxa oladi.
        self._info_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        _apply_font(self._info_value, 21, bold=True, families=_MONO_FAMILIES,
                    extra="color: {};".format(COLORS["text"]))
        info_layout.addWidget(self._info_value)

        self._info_note = QLabel("")
        self._info_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_note.setWordWrap(True)
        _apply_font(self._info_note, 12,
                    extra="color: {}; padding-top: 4px;".format(COLORS["text_muted"]))
        self._info_note.hide()
        info_layout.addWidget(self._info_note)

        self._info.hide()
        details_layout.addWidget(self._info)

        self.message = MessageBar()
        details_layout.addWidget(self.message)

        # Amallar (MD3: ikkilamchi chapda, asosiy o'ngda)
        self._actions = QWidget()
        self._actions.setStyleSheet("background: transparent;")
        buttons = QHBoxLayout(self._actions)
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(10)

        self.exit_btn = QPushButton("Chiqish")
        self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exit_btn.setStyleSheet(outlined_button_style(44, "neutral"))
        self.exit_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.exit_btn.clicked.connect(self.exit_requested.emit)
        buttons.addWidget(self.exit_btn, 1)

        self.retry_btn = QPushButton("Qayta urinish")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Chiqish bilan BIR XIL shakl, faqat yashil urg'u - modalda
        # ikkalasi ham teng huquqli amal va shakl farqi ortiqcha
        # shovqin qo'shardi.
        self.retry_btn.setStyleSheet(outlined_button_style(44, "primary"))
        self.retry_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.retry_btn.setDefault(True)
        self.retry_btn.clicked.connect(self.start)
        buttons.addWidget(self.retry_btn, 1)

        details_layout.addWidget(self._actions)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addSpacing(14)

        version = QLabel("v{}".format(APP_VERSION))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: rgba(255,255,255,0.45); background: transparent;")
        outer.addWidget(version, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()

        self._set_actions_visible(False)
        self._show_state("loading", _CHECKING_TITLE, _CHECKING_TEXT)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Karta oyna bilan birga o'lchamini o'zgartiradi.
        width = int(self.width() * _CARD_WIDTH_RATIO)
        self._card.setFixedWidth(max(_CARD_MIN_WIDTH, min(_CARD_MAX_WIDTH, width)))

    # ------------------------------------------------------------------
    # Holatni ko'rsatish
    # ------------------------------------------------------------------
    def _show_state(self, state: str, title: str, subtitle: str,
                    *, emphasis: bool = False) -> None:
        """
        Nishon, sarlavha va matnni BIRGALIKDA almashtiradi.

        Uchalasi har doim birga o'zgaradi - alohida qo'yilsa, holatlar
        aralashib qolishi mumkin (yashil nishon ustida qizil matn).
        """
        self._badge.set_state(state)
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        # `emphasis` - "Adminga murojaat qiling!" kabi CHAQIRIQ matni:
        # u ma'lumot emas, harakat ko'rsatmasi va shunday ko'rinishi
        # kerak. Aks holda operator uni navbatdagi izoh deb o'qib
        # o'tkazib yuboradi.
        accent = {"error": COLORS["error"], "warning": COLORS["warning"]}.get(
            state, COLORS["text_secondary"]
        )
        _apply_font(
            self._subtitle,
            16 if emphasis else 14,
            bold=emphasis,
            extra="color: {};".format(
                accent if emphasis else COLORS["text_secondary"]
            ),
        )

    def _show_ip(self, value: str, note: str = "") -> None:
        self._info_value.setText(value or "aniqlanmadi")
        self._info_note.setText(note)
        self._info_note.setVisible(bool(note))
        self._info.show()
        self._sync_details()

    def _set_actions_visible(self, visible: bool) -> None:
        self._actions.setVisible(visible)
        self._sync_details()

    def _sync_details(self) -> None:
        """
        Pastki blok faqat ichida ko'rsatiladigan narsa bo'lsa turadi.

        `isHidden()` ishlatiladi, `isVisible()` EMAS. Farqi shu yerda
        hal qiluvchi: ota-ona yashiringan bo'lsa, bola `show()` qilingan
        bo'lsa ham `isVisible()` `False` qaytaradi - natijada blok
        hech qachon ochilmaydigan holatga tushib qolardi.
        """
        self._details.setVisible(
            not self._info.isHidden()
            or not self._actions.isHidden()
            or bool(self.message.text())
        )

    # ------------------------------------------------------------------
    # Tekshiruv
    # ------------------------------------------------------------------
    def start(self) -> None:
        """
        Tekshiruvni boshlaydi (ishga tushishda va "Qayta urinish" da).

        Public IP so'rovi shu chaqiruv ichida kutilishi mumkin
        (`DeviceRepository.PUBLIC_IP_WAIT_SECONDS`), shuning uchun u fon
        thread'ida - UI muzlamaydi.
        """
        if self._busy:
            return
        self._busy = True
        self._set_actions_visible(False)
        self._info.hide()
        self.message.clear_message()
        self._sync_details()
        self._show_state("loading", _CHECKING_TITLE, _CHECKING_TEXT)

        worker = ApiWorker(self._repo.preflight, parent=self)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failed)
        self._workers.run(worker)

    def _on_success(self, result) -> None:
        self._busy = False
        # Holat ishlovchisi ekranni TO'LIQ o'zi belgilaydi va oldingi
        # holatdan nima qolganiga tayanmaydi. `start()` ham tozalaydi,
        # lekin ikkalasi bir-birini nazarda tutsa, oqim biroz
        # o'zgarganda muvaffaqiyat ekranida eski xato xabari qolib
        # ketardi.
        self.message.clear_message()
        self._set_actions_visible(False)
        result = result or {}
        zone = (result.get("zone") or {}).get("name") or ""
        region = (result.get("region") or {}).get("name") or ""
        public_ip = result.get("public_ip") or ""

        if zone:
            subtitle = "{}{}".format(zone, " · {}".format(region) if region else "")
        elif not result.get("enforced"):
            # Ro'yxat bo'sh - server tekshiruvni o'chirilgan deb hisoblaydi.
            # Buni yashirish mumkin emas: o'rnatish tugallanmagan holat.
            subtitle = "IP cheklovi sozlanmagan (ro'yxat bo'sh)"
        else:
            # Manzil ro'yxatda, lekin binoga bog'lanmagan (global yozuv).
            subtitle = "Bino aniqlanmadi — manzil global ro'yxatda"

        self._show_state("ready", "Tarmoq tasdiqlandi", subtitle)

        note = ""
        if result.get("matches_observed") is False:
            # Server so'rovni boshqa manzildan kelgan deb ko'ryapti -
            # yo'lda proxy yoki VPN bor. Ruxsatga ta'sir qilmaydi
            # (qaror public IP bo'yicha), lekin nosozlik qidirilganda
            # birinchi ma'lumot shu bo'ladi.
            note = "Server so'rovni {} manzilidan ko'ryapti".format(
                result.get("observed_ip") or "-"
            )
        self._show_ip(public_ip, note)

        log.info("Preflight o'tdi: ip=%s bino=%s", public_ip or "-", zone or "-")
        self._report_attempt(entered_login=True)
        # Natija ko'rinib turishi uchun qisqa pauza, keyin login.
        QTimer.singleShot(_HANDOFF_DELAY_MS, lambda: self.passed.emit(result))

    def _on_failed(self, message: str, code: str) -> None:
        self._busy = False
        # `_on_success` dagi bilan bir xil qoida: ishlovchi ekranni
        # TO'LIQ o'zi belgilaydi. Har bir tarmoq holati o'z xabarini
        # ko'rsatmaydi (masalan ro'yxat bo'shligi), shuning uchun
        # tozalash bo'lmasa oldingi urinishdan qolgan matn boshqa
        # sababning ustida turib qolardi.
        self.message.clear_message()
        self._set_actions_visible(True)

        # Manzil client keshidan olinadi - bu AYNAN serverga yuborilgan
        # qiymat. Uni server javobidan olish ham mumkin edi, lekin
        # `ApiWorker` faqat (xabar, kod) juftligini uzatadi va butun
        # signal imzosini bitta ekran uchun o'zgartirish noto'g'ri
        # almashuv bo'lardi.
        public_ip = system_info.public_ip()

        if code in ("ip_not_allowed", "ip_allowlist_empty"):
            # Ikkalasida ham operator uchun holat bir xil - kirish
            # to'xtadi va uni O'ZI hal qila olmaydi. Farq faqat
            # administrator nima qilishida, shuning uchun u pastdagi
            # izohlarda qoladi.
            self._show_state(
                "error", "Kirish to'xtatildi", "Adminga murojaat qiling!", emphasis=True
            )
            if code == "ip_not_allowed":
                self._show_ip(public_ip, "Bu manzil ruxsat etilganlar ro'yxatida yo'q")
                self.message.show_message(
                    "Kompyuter ro'yxatga olinmagan tarmoqdan ulanmoqda.", "error"
                )
            else:
                # Ro'yxat bo'shligi - ADMINISTRATOR sozlamasidagi holat.
                # Operator uni o'qib hech narsa qila olmaydi, shuning
                # uchun ekranda faqat "adminga murojaat qiling" qoladi;
                # aniq sabab serverdagi `client_access.log` da va
                # `WARNING` darajasidagi log yozuvida.
                self._show_ip(public_ip)
        elif code == "public_ip_unknown":
            self._show_state(
                "warning",
                "Internet aloqasi yo'q",
                "Tarmoq ulanishini tekshiring",
                emphasis=True,
            )
            self._info.hide()
            self.message.show_message(
                "Kompyuterning internetga chiqish manzilini aniqlab bo'lmadi.",
                "warning",
            )
        elif code == "throttled":
            self._show_state("warning", "Juda ko'p urinish", "Biroz kutib qayta urining")
            self._info.hide()
            self.message.show_message(message, "warning")
        else:
            # Tarmoq xatosi (`network`) va kutilmagan javoblar bir xil
            # ko'rsatiladi: ikkalasida ham operator qila oladigan yagona
            # narsa - aloqani tekshirib qayta urinish.
            self._show_state(
                "error", "Server bilan aloqa yo'q", "Adminga murojaat qiling!",
                emphasis=True,
            )
            self._info.hide()
            self.message.show_message(
                "Proktorlik serveriga ulanib bo'lmadi. Tarmoq ulanishini "
                "tekshiring.", "error"
            )

        self._sync_details()
        log.warning("Preflight to'xtatdi (%s): %s", code or "-", message)
        self._report_attempt(entered_login=False, code=code)

    # ------------------------------------------------------------------
    def _report_attempt(self, *, entered_login: bool, code: str = "") -> None:
        """
        Urinishni serverdagi jurnalga yozdiradi - fon thread'ida.

        Natijadan QAT'IY NAZAR yuboriladi: jurnalning butun qiymati
        muvaffaqiyatsiz urinishlarni ko'rsatishda, ya'ni "kira olmadi"
        holati "kirdi" dan muhimroq. Xatolari yutiladi
        (`DeviceRepository.report_access_attempt`), shuning uchun
        `failed` signaliga ulanish shart emas.
        """
        worker = ApiWorker(
            self._repo.report_access_attempt,
            entered_login=entered_login,
            code=code,
            parent=self,
        )
        self._workers.run(worker)

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self._workers.wait_all()
