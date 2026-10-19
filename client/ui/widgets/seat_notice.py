"""
Kompyuter broni natijasi — JSHSHIR sahifasida.

Server javobi TUZILGAN (`error.details.seat` / `current`): client
raqamni xabar matnidan ajratib olmaydi. Sabab — ekranning maqsadi: bu
yerda operatorga "rad etildi" degan matn emas, TALABGORNI QAYERGA
YUBORISH kerakligi kerak. Shuning uchun asosiy element — yirik stol
raqami, xabar matni esa uning ostidagi izoh.

To'rt holat va ular ATAYLAB farqli ko'rinadi, chunki operator har
birida boshqa ish qiladi:

    wrong_computer            - talabgorni ko'rsatilgan stolga
                                yo'naltiradi ("bu -> borishi kerak");
    seat_out_of_service       - talabgorning kompyuteri buzilgan:
                                administrator uni ko'chiradi;
    seat_not_booked           - talabgor joysiz: administrator
                                biriktiradi;
    device_binding_mismatch   - talabgor to'g'ri stolda, lekin dastur
                                boshqa kompyuterga biriktirilgan.

Erkin joylashuvda (imtihon profilida `is_booking` o'chiq) gap talabgorning
OLDINDAN berilgan joyi emas, u HOZIR o'tirgan stol haqida — operatorning
ishi ham boshqa: talabgorni boshqa bo'sh kompyuterga o'tkazish. Shuning
uchun bu kodlar alohida va kartada faqat "BU KOMPYUTER" ko'rinadi:

    computer_not_in_schedule   - stol sessiyaga kiritilmagan (yoki
                                 mashina ro'yxatda yo'q);
    computer_out_of_service    - stol buzilgan deb belgilangan;
    computer_busy              - stol boshqa talabgorniki;
    candidate_already_finished - talabgor bu sessiyada yakunlagan.

KO'RINISH — sahifadagi boshqa xabarlar bilan BITTA komponent
(`notice.Notice`, MD3 tonal blok): ikonka, sarlavha, keyingi qadam, stol
kataklari, eng pastda server matni. Ilgari bu alohida oq karta edi va
oddiy xatolar boshqa uslubda chiqardi.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ui.styles import COLORS
from ui.widgets.notice import TONES, Notice

#: Kod -> (sarlavha, keyingi qadam, ohang).
_STATES = {
    # Matnlar QISQA: blok JSHSHIR tugmasi ostida turadi va ekran oldida
    # talabgor bor. Qaysi panel sahifasida tuzatilishi — administratorning
    # ishi (u buni biladi); server matni tooltip'da (`Notice` ixcham shakli).
    "wrong_computer": (
        "Talabgor boshqa kompyuterga biriktirilgan",
        "Talabgorni ko‘rsatilgan kompyuterga yo‘naltiring.",
        "error",
    ),
    "seat_out_of_service": (
        "Talabgorning kompyuteri nosoz",
        "Administrator talabgorni boshqa kompyuterga ko‘chirsin.",
        "error",
    ),
    "seat_not_booked": (
        "Talabgor kompyuterga biriktirilmagan",
        "Administrator talabgorni shu test sessiyasiga biriktirsin.",
        "warning",
    ),
    "device_binding_mismatch": (
        "Dastur boshqa kompyuterga biriktirilgan",
        "Talabgor to‘g‘ri joyda. Administrator dasturni shu kompyuterga qayta biriktirsin.",
        "warning",
    ),
    "computer_not_in_schedule": (
        "Bu kompyuter test sessiyasida yo‘q",
        "Talabgorni boshqa kompyuterga o‘tkazing yoki administratorga murojaat qiling.",
        "warning",
    ),
    "computer_out_of_service": (
        "Bu kompyuter nosoz deb belgilangan",
        "Talabgorni boshqa bo‘sh kompyuterga o‘tkazing.",
        "error",
    ),
    "computer_busy": (
        "Bu kompyuter boshqa talabgorga biriktirilgan",
        "Talabgorni boshqa bo‘sh kompyuterga o‘tkazing.",
        "warning",
    ),
    "candidate_already_finished": (
        "Talabgor imtihonni yakunlagan",
        "Qayta kirishga faqat administrator ruxsat beradi.",
        "warning",
    ),
}

#: `SeatNotice` ko'rsatadigan xato kodlari — sahifa shular uchun oddiy
#: xabar qatorini ishlatmaydi.
SEAT_CODES = frozenset(_STATES)


def _caption(text: str, color: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        "font-size: 10px; font-weight: 800; letter-spacing: 1.2px; "
        "background: transparent; color: {};".format(color)
    )
    return label


class _SeatTile(QFrame):
    """
    Bitta stol: yorliq, yirik raqam va ostida bino/viloyat.

    Ikkala katak BIR XIL tuzilmada (yorliq / raqam / joy) va joy qatori
    yashirilganda ham o'rnini saqlaydi: ilgari "BU KOMPYUTER" katagida joy
    qatori yo'q edi va uning raqami qo'shni katakdagidan pastroq tushardi.
    """

    def __init__(self, name: str, *, primary: bool, compact: bool = False) -> None:
        super().__init__()
        self.setObjectName(name)
        # Tonal fon ustida: maqsad — "primary container" (ko'z birinchi
        # shunga tushadi), hozirgi mashina — eng och sirt.
        self.setStyleSheet(
            "QFrame#{} {{ background-color: {}; border: none; border-radius: 12px; }}".format(
                name,
                COLORS["primary_container"] if primary else COLORS["surface_container_lowest"],
            )
        )
        box = QVBoxLayout(self)
        # Ixcham shaklda raqam 24/20 px: stol raqami baribir xabarning eng
        # yirik elementi bo'lib qoladi, blok esa ikki baravar pasayadi.
        box.setContentsMargins(*((10, 5, 10, 6) if compact else (14, 10, 14, 10)))
        box.setSpacing(0)

        accent = COLORS["primary_dark"] if primary else COLORS["text_muted"]
        self.caption = _caption("", accent)
        box.addWidget(self.caption)

        self.number = QLabel("—")
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.number.setStyleSheet(
            "font-size: {}px; font-weight: 800; background: transparent; color: {};".format(
                (24 if primary else 20) if compact else (36 if primary else 30),
                COLORS["primary_deep"] if primary else COLORS["text_secondary"],
            )
        )
        box.addWidget(self.number)

        self.place = QLabel("")
        self.place.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.place.setWordWrap(True)
        self.place.setStyleSheet(
            "font-size: {}px; font-weight: 600; background: transparent; color: {};".format(
                11 if compact else 12,
                COLORS["primary_deep"] if primary else COLORS["text_secondary"],
            )
        )
        retain = self.place.sizePolicy()
        retain.setRetainSizeWhenHidden(True)
        self.place.setSizePolicy(retain)
        box.addWidget(self.place)

    def set_seat(self, caption: str, seat: Optional[dict], *, show_place: bool = True) -> None:
        seat = seat or {}
        self.caption.setText(caption)
        number = seat.get("number")
        self.number.setText("№{}".format(number) if number else (seat.get("inventory_code") or "—"))
        self.setToolTip(seat.get("label") or "")
        place = " · ".join(
            part for part in (seat.get("zone_name"), seat.get("region_name")) if part
        )
        # Matn har doim yoziladi (o'lcham bir xil bo'lishi uchun), faqat
        # ko'rinishi boshqariladi.
        self.place.setText(place or " ")
        self.place.setVisible(bool(place) and show_place)


class SeatNotice(Notice):
    """Bron bo'yicha rad javobi — JSHSHIR tugmasi ostidagi MD3 blok."""

    def __init__(self, parent=None, *, compact: bool = False) -> None:
        super().__init__(parent, compact=compact)
        self._tile_compact = compact
        # Kataklar o'z konteynerida: hech biri ko'rinmaydigan kodda
        # (`seat_not_booked`) konteyner yashirinadi va bo'shliq qolmaydi.
        self.tiles = QWidget()
        self.tiles.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self.tiles)
        row.setContentsMargins(0, 6 if compact else 8, 0, 2)
        row.setSpacing(8 if compact else 10)
        self.current = _SeatTile("seatCurrent", primary=False, compact=compact)
        row.addWidget(self.current, 1)
        self.arrow = QLabel("→")
        self.arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row.addWidget(self.arrow)
        self.target = _SeatTile("seatTarget", primary=True, compact=compact)
        row.addWidget(self.target, 1)
        self.extra.addWidget(self.tiles)
        self.hide()

    def show_problem(self, code: str, message: str, details: Optional[dict]) -> None:
        title, hint, tone = _STATES.get(code, (message, "", "error"))
        # Sarlavha serverdan kelgan bo'lsa (noma'lum kod) - pastda takrorlanmaydi.
        self.show_notice(tone, title, hint, "" if title == message else (message or ""))
        on_color = TONES.get(tone, TONES["error"])[1]
        self.arrow.setStyleSheet(
            "font-size: {}px; font-weight: 700; background: transparent; color: {};".format(
                20 if self._tile_compact else 26, on_color)
        )

        details = details if isinstance(details, dict) else {}
        seat, current = details.get("seat"), details.get("current")

        # Yo'nalish ("bu -> u yerga") faqat talabgor BOSHQA stolga
        # borishi kerak bo'lganda; qolgan holatlarda — faqat joyning
        # o'zi (qaysi kompyuter buzilgan / qaysi biriga biriktirilgan).
        directed = code == "wrong_computer" and current is not None
        # Erkin joylashuv kodlarida talabgorning joyi yo'q - muammo
        # turgan stolning o'zi ko'rsatiladi (operator raqamni ko'rib,
        # qaysi stol ekanini administratorga aytadi).
        here_only = seat is None and current is not None
        self.current.setVisible(directed or here_only)
        self.arrow.setVisible(directed)
        self.target.setVisible(seat is not None)
        self.tiles.setVisible(directed or here_only or seat is not None)
        if directed:
            self.current.set_seat("BU KOMPYUTER", current, show_place=(
                (current or {}).get("zone_id") != (seat or {}).get("zone_id")
            ))
        elif here_only:
            self.current.set_seat("BU KOMPYUTER", current, show_place=False)
        if seat is not None:
            caption = {
                "wrong_computer": "BORISHI KERAK",
                "seat_out_of_service": "BIRIKTIRILGAN (NOSOZ)",
                "device_binding_mismatch": "TALABGOR JOYI",
            }.get(code, "JOY")
            self.target.set_seat(caption, seat)
        # Balandlik QAYTA o'lchanadi: `show_notice` uni kataklar
        # ko'rinishi o'zgarishidan OLDIN o'lchagan. Usiz kataklar bilan
        # xabardan keyin katakSIZ xabar oldingi balandlikda, ichida bo'sh
        # joy bilan qolardi.
        self._fit()
