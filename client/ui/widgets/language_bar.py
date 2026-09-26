"""
Klaviatura tili almashtirgichi - bitta ixcham tugma.

NIMA UCHUN BITTA TUGMA. Ekranda faqat JORIY til ko'rinadi va
bosilganda keyingisiga o'tadi. Bu tanlov ixchamlik foydasiga:
almashtirgich imtihon oynasining USTIDA turadi va u yerda har bir
piksel test platformasiga tegishli. Uch segmentli variant uch
barobar joy egallardi, holbuki operator uni kuniga bir-ikki marta
bosadi.

Buning evaziga aniq tilga o'tish uchun bir necha bosish kerak
bo'lishi mumkin (uch tilda - ko'pi bilan ikkita). Shuning uchun
tooltip KEYINGI tilni ham aytadi: operator nima bo'lishini
oldindan biladi va "qaysi biriga tushdi?" deb sinab ko'rmaydi.

JOYLASHUV - PASTKI CHAP BURCHAK (`MainWindow._place_language_bar`).
O'ng tomonda imtihon oynasining o'z paneli turadi (aloqa, texnik
muammo, yakunlash); til esa KIRITISHGA tegishli va boshqa chetda
turgani ma'qul - ikkalasi bir joyda bo'lsa, shoshilgan operator
"yakunlash" o'rniga tilni bosib qo'yishi mumkin.

Vidjet OS holatiga TAYANADI. Ichki "tanlangan til" o'zgaruvchisi
yo'q: til tizim vositalari bilan ham o'zgarishi mumkin va o'shanda
ichki holat OS bilan ajralib ketardi. Joriy qiymat davriy ravishda
OS'dan so'raladi.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QPushButton

from services import keyboard_layout
from ui.styles import COLORS

log = logging.getLogger(__name__)

#: Joriy tilni OS'dan qayta so'rash oralig'i (ms).
#:
#: Til dastur tashqarisida ham o'zgarishi mumkin (tugmalar
#: bloklanmagan bo'lsa). Sekundiga bir marta so'rash ikkita yengil
#: WinAPI chaqiruvi - sezilarli yuk emas, lekin tugma ekrandagi
#: haqiqatdan orqada qolmaydi.
_POLL_INTERVAL_MS = 1000

#: Tugma o'lchami.
#:
#: Suzuvchi paneldagi ikonkalardan (38 px) BIR OZ KICHIK va bu
#: ataylab: ular imtihonni boshqaradigan amallar (texnik muammo,
#: yakunlash), til almashtirgich esa kuniga bir-ikki marta
#: bosiladi. Ekranning qarama-qarshi burchaklarida turgani uchun
#: 4-6 px farq ko'zga tashlanmaydi, lekin element o'z og'irligiga
#: qaytadi - u imtihon tugmalari bilan raqobatlashmaydi.
#:
#: Pastga tushirish chegarasi bor: matn ikki-uch harf ("UZ", "РУ")
#: va tugma bosish nishoni sifatida 32 px dan kichik bo'lsa,
#: sichqoncha bilan tegish qiyinlashadi.
_WIDTH = 48
_HEIGHT = 32


def _button_qss() -> str:
    """
    MD3 "outlined button" - pill shaklida.

    Kartaning o'zi TUGMA: ichma-ich (oq karta + ichida rangli
    tugma) ikkita yumaloq shakl bitta belgi uchun ortiqcha
    og'irlik berardi. Fon oq, ya'ni u imtihon sahifasining
    ustida aniq ajralib turadi.
    """
    return """
        QPushButton {{
            background-color: {surface};
            color: {primary_dark};
            border: 1px solid {border};
            border-radius: {radius}px;
            padding: 0;
            margin: 0;
            min-width: {width}px;
            min-height: {height}px;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.4px;
        }}
        QPushButton:hover {{
            background-color: {primary_soft};
            border-color: {primary};
        }}
        QPushButton:pressed {{
            background-color: {primary_soft};
            color: {primary};
        }}
    """.format(radius=_HEIGHT // 2, width=_WIDTH, height=_HEIGHT, **COLORS)


class LanguageBar(QPushButton):
    """Joriy klaviatura tili; bosilganda keyingisiga o'tadi."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layouts = keyboard_layout.available()
        self._active_hkl = 0

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(_WIDTH, _HEIGHT)
        self.setStyleSheet(_button_qss())
        self.clicked.connect(self._cycle)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

        # Til bitta bo'lsa almashtiradigan narsa yo'q: tugma faqat
        # joy egallab, hech qanday amal taklif qilmasdi.
        self.setVisible(len(self._layouts) > 1)
        # Matn DARHOL qo'yiladi: `showEvent` gacha tugma bo'sh
        # turardi va oyna ochilgan lahzada ekranda tushuntirib
        # bo'lmaydigan bo'sh tugma ko'rinardi.
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Tugma matnini OS holati bo'yicha yangilaydi."""
        current = keyboard_layout.current_hkl(self._window_handle())
        if current == self._active_hkl:
            return
        self._active_hkl = current

        active = self._find(current)
        self.setText(active.code if active else "—")
        self.setToolTip(self._tooltip(active))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        # Ko'rinmaydigan vidjet uchun so'rov yuritish bekorga ish.
        self._timer.stop()
        super().hideEvent(event)

    # ------------------------------------------------------------------
    def _cycle(self) -> None:
        """Ro'yxatdagi KEYINGI tilga o'tadi (oxiridan boshiga)."""
        following = self._next()
        if following is None:
            return
        handle = self._window_handle()
        if handle and keyboard_layout.activate(following.hkl, handle):
            # Windows xabarni asinxron qayta ishlaydi - holatni
            # darhol emas, keyingi siklda so'raymiz.
            QTimer.singleShot(60, self.refresh)

    def _next(self):
        """Joriydan keyingi til. Joriysi topilmasa - birinchisi."""
        if not self._layouts:
            return None
        index = self._index_of(self._active_hkl)
        if index is None:
            return self._layouts[0]
        return self._layouts[(index + 1) % len(self._layouts)]

    def _find(self, hkl: int):
        index = self._index_of(hkl)
        return self._layouts[index] if index is not None else None

    def _index_of(self, hkl: int):
        """
        Faqat til identifikatori (past 16 bit) solishtiriladi.

        Bitta til uchun bir nechta HKL bo'lishi mumkin (masalan
        turli klaviatura joylashuvlari) va ular bir xil tilni
        bildiradi - to'liq qiymat bo'yicha solishtirish tugmani
        "noma'lum til" holatiga tushirardi.
        """
        for index, item in enumerate(self._layouts):
            if (item.hkl & 0xFFFF) == (hkl & 0xFFFF):
                return index
        return None

    def _tooltip(self, active) -> str:
        """Joriy til + bosilganda nima bo'lishi."""
        following = self._next()
        current_name = active.name if active else "Noma'lum til"
        if following is None or following is active:
            return current_name
        return "{}\nBosing: {}".format(current_name, following.name)

    def _window_handle(self) -> int:
        """
        Asosiy oynaning HWND'i.

        Xabar AYNAN yuqori darajali oynaga yuborilishi kerak:
        Windows kirish tilini oyna bo'yicha yuritadi va bola
        vidjetning o'z HWND'i yo'q.
        """
        window = self.window()
        if window is None:
            return 0
        try:
            return int(window.winId())
        except (RuntimeError, TypeError):
            return 0
