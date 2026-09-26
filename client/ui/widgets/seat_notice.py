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
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ui.styles import COLORS, surface_container_style

#: Kod -> (sarlavha, keyingi qadam, ohang).
_STATES = {
    "wrong_computer": (
        "Talabgor boshqa kompyuterga biriktirilgan",
        "Talabgorni ko‘rsatilgan kompyuterga yo‘naltiring va JSHSHIR’ni o‘sha yerda kiriting.",
        "error",
    ),
    "seat_out_of_service": (
        "Talabgorning kompyuteri buzilgan deb belgilangan",
        "Administrator talabgorni «Kompyuter bronlari» sahifasida boshqa kompyuterga ko‘chirishi kerak.",
        "error",
    ),
    "seat_not_booked": (
        "Talabgor hech qaysi kompyuterga biriktirilmagan",
        "Administrator uni «Kompyuter bronlari» sahifasida shu test sessiyasiga biriktirishi kerak.",
        "warning",
    ),
    "device_binding_mismatch": (
        "Talabgor to‘g‘ri kompyuterda, lekin dastur boshqa kompyuterga biriktirilgan",
        "Administrator «Qurilma tokenlari» sahifasida qurilmani shu kompyuterga qayta biriktirishi kerak.",
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
    """Bitta stol: yorliq, yirik raqam va ostida bino/viloyat."""

    def __init__(self, name: str, *, primary: bool) -> None:
        super().__init__()
        self.setObjectName(name)
        # Maqsad — MD3 "primary container" (ko'z birinchi shunga tushadi),
        # hozirgi mashina — neytral "surface container".
        self.setStyleSheet(surface_container_style(name, tone="high" if primary else "low"))
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(2)

        accent = COLORS["primary_dark"] if primary else COLORS["text_muted"]
        self.caption = _caption("", accent)
        box.addWidget(self.caption)

        self.number = QLabel("—")
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.number.setStyleSheet(
            "font-size: {}px; font-weight: 800; background: transparent; color: {};".format(
                44 if primary else 28,
                COLORS["primary_deep"] if primary else COLORS["text_secondary"],
            )
        )
        box.addWidget(self.number)

        self.place = QLabel("")
        self.place.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.place.setWordWrap(True)
        self.place.setStyleSheet(
            "font-size: 13px; font-weight: 600; background: transparent; color: {};".format(
                COLORS["primary_deep"] if primary else COLORS["text_secondary"]
            )
        )
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
        self.place.setText(place if show_place else "")
        self.place.setVisible(bool(place) and show_place)


class SeatNotice(QFrame):
    """Bron bo'yicha rad javobi — JSHSHIR kartasining ostida."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("role", "card")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 22)
        root.setSpacing(12)

        self.title = QLabel("")
        self.title.setWordWrap(True)
        root.addWidget(self.title)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(
            "font-size: 14px; background: transparent; color: {};".format(COLORS["text_secondary"])
        )
        root.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.current = _SeatTile("seatCurrent", primary=False)
        row.addWidget(self.current, 2)
        self.arrow = QLabel("→")
        self.arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow.setStyleSheet(
            "font-size: 30px; font-weight: 700; background: transparent; color: {};".format(
                COLORS["text_muted"]
            )
        )
        row.addWidget(self.arrow)
        self.target = _SeatTile("seatTarget", primary=True)
        row.addWidget(self.target, 3)
        self._tiles = row
        root.addLayout(row)

        # Server matni — oxirida, kichik: u yuqoridagining NUSXASI emas,
        # dalil (administrator bilan gaplashganda aynan shu aytiladi).
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setStyleSheet(
            "font-size: 12px; background: transparent; color: {};".format(COLORS["text_muted"])
        )
        root.addWidget(self.detail)
        self.hide()

    def show_problem(self, code: str, message: str, details: Optional[dict]) -> None:
        title, hint, tone = _STATES.get(code, (message, "", "error"))
        color = COLORS["error"] if tone == "error" else COLORS["warning"]
        self.title.setText(title)
        self.title.setStyleSheet(
            "font-size: 18px; font-weight: 700; background: transparent; color: {};".format(color)
        )
        self.hint.setText(hint)
        self.detail.setText(message or "")

        details = details if isinstance(details, dict) else {}
        seat, current = details.get("seat"), details.get("current")

        # Yo'nalish ("bu -> u yerga") faqat talabgor BOSHQA stolga
        # borishi kerak bo'lganda; qolgan holatlarda — faqat joyning
        # o'zi (qaysi kompyuter buzilgan / qaysi biriga biriktirilgan).
        directed = code == "wrong_computer" and current is not None
        self.current.setVisible(directed)
        self.arrow.setVisible(directed)
        self.target.setVisible(seat is not None)
        if directed:
            self.current.set_seat("BU KOMPYUTER", current, show_place=(
                (current or {}).get("zone_id") != (seat or {}).get("zone_id")
            ))
        if seat is not None:
            caption = {
                "wrong_computer": "BORISHI KERAK",
                "seat_out_of_service": "BIRIKTIRILGAN (BUZILGAN)",
                "device_binding_mismatch": "TALABGOR JOYI",
            }.get(code, "JOY")
            self.target.set_seat(caption, seat)
        self.show()
