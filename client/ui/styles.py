"""
Dizayn tizimi - yashil urg'uli, zamonaviy va toza.

Barcha ranglar SHU YERDA. Sahifalarda hex kod yozilmaydi: mavzu
o'zgarsa (masalan boshqa muassasa brendi) o'zgarish bitta faylda qoladi.
"""

# ---------------------------------------------------------------------
# Palitra
#
# Yashil - tizimning asosiy rangi: "ruxsat berildi / tayyor" holati
# proktorlikdagi eng ko'p uchraydigan ijobiy signal. Qizil FAQAT
# haqiqiy to'siq uchun ishlatiladi, aks holda u ko'zga tashlanmay
# qoladi.
# ---------------------------------------------------------------------
COLORS = {
    "primary": "#16A34A",
    "primary_light": "#22C55E",
    "primary_dark": "#15803D",
    "primary_deep": "#064E3B",
    "primary_soft": "#DCFCE7",
    "accent": "#0EA5E9",
    "background": "#F1F5F4",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFB",
    "border": "#E2E8F0",
    "border_strong": "#CBD5E1",
    "text": "#0F172A",
    "text_secondary": "#64748B",
    "text_muted": "#94A3B8",
    "error": "#DC2626",
    "error_soft": "#FEE2E2",
    "warning": "#D97706",
    "warning_soft": "#FEF3C7",
    "success": "#16A34A",
    "success_soft": "#DCFCE7",
    "info_soft": "#E0F2FE",
    "on_primary": "#FFFFFF",
}

FONT_FAMILY = "'Segoe UI', 'Inter', 'Roboto', sans-serif"

RADIUS = 14
RADIUS_LG = 22

GLOBAL_STYLESHEET = """
QWidget {{
    background-color: {background};
    color: {text};
    font-family: {font};
    font-size: 15px;
}}

QLabel {{
    background: transparent;
}}
QLabel[role="title"] {{
    font-size: 26px;
    font-weight: 700;
    color: {text};
}}
QLabel[role="subtitle"] {{
    font-size: 15px;
    color: {text_secondary};
}}
QLabel[role="caption"] {{
    font-size: 13px;
    color: {text_muted};
}}
QLabel[role="field"] {{
    font-size: 13px;
    font-weight: 600;
    color: {text_secondary};
}}
QLabel[role="value"] {{
    font-size: 16px;
    font-weight: 600;
    color: {text};
}}

QFrame[role="card"] {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: {radius_lg}px;
}}
QFrame[role="panel"] {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: {radius}px;
}}
QFrame[role="divider"] {{
    background-color: {border};
    max-height: 1px;
    border: none;
}}

QPushButton {{
    background-color: {primary};
    color: {on_primary};
    border: none;
    border-radius: {radius}px;
    padding: 12px 26px;
    font-size: 15px;
    font-weight: 600;
    min-height: 44px;
}}
QPushButton:hover {{
    background-color: {primary_light};
}}
QPushButton:pressed {{
    background-color: {primary_dark};
}}
QPushButton:disabled {{
    background-color: {border};
    color: {text_muted};
}}

QPushButton[variant="ghost"] {{
    background-color: transparent;
    color: {text_secondary};
    border: 1px solid {border_strong};
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {surface_alt};
    color: {text};
}}
QPushButton[variant="danger"] {{
    background-color: {error};
}}
QPushButton[variant="danger"]:hover {{
    background-color: #EF4444;
}}
QPushButton[variant="link"] {{
    background: transparent;
    color: {primary_dark};
    border: none;
    padding: 6px 10px;
    min-height: 28px;
    font-weight: 600;
}}
QPushButton[variant="link"]:hover {{
    color: {primary};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {surface};
    border: 1.5px solid {border};
    border-radius: {radius}px;
    padding: 12px 16px;
    font-size: 15px;
    selection-background-color: {primary_light};
}}
QLineEdit:hover, QTextEdit:hover {{
    border-color: {border_strong};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {primary};
    padding: 11px 15px;
}}
QLineEdit:disabled {{
    background-color: {surface_alt};
    color: {text_muted};
}}

QComboBox {{
    background-color: {surface};
    border: 1.5px solid {border};
    border-radius: {radius}px;
    padding: 11px 16px;
    font-size: 15px;
    min-height: 44px;
}}
QComboBox:hover {{
    border-color: {border_strong};
}}
QComboBox:focus {{
    border: 2px solid {primary};
}}
QComboBox:disabled {{
    background-color: {surface_alt};
    color: {text_muted};
}}
QComboBox::drop-down {{
    border: none;
    width: 34px;
}}
QComboBox QAbstractItemView {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 6px;
    selection-background-color: {primary_soft};
    selection-color: {text};
    outline: none;
}}

QProgressBar {{
    border: none;
    border-radius: 4px;
    background-color: {border};
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {primary};
    border-radius: 4px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {border_strong};
    border-radius: 5px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QToolTip {{
    background-color: {text};
    color: #FFFFFF;
    border: none;
    padding: 6px 10px;
    border-radius: 8px;
}}
""".format(
    font=FONT_FAMILY,
    radius=RADIUS,
    radius_lg=RADIUS_LG,
    **COLORS,
)


def primary_button_style(height: int = 52) -> str:
    """Asosiy amal tugmasi - gradient bilan (login, davom etish)."""
    return """
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {primary_dark}, stop:1 {primary});
            color: {on_primary};
            border: none;
            border-radius: {radius}px;
            font-size: 15px;
            font-weight: 700;
            letter-spacing: 0.6px;
            min-height: {height}px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {primary}, stop:1 {primary_light});
        }}
        QPushButton:pressed {{
            background: {primary_dark};
        }}
        QPushButton:disabled {{
            background: {border};
            color: {text_muted};
        }}
    """.format(radius=height // 2, height=height, **COLORS)


def outlined_button_style(height: int = 44, tone: str = "neutral") -> str:
    """
    Material Design 3 "outlined" tugmasi.

    Bir qatordagi tugmalar BIR XIL shaklda bo'ladi va faqat RANG bilan
    ajraladi. To'ldirilgan (filled) tugma yonida outlined turgan
    variant ham ishlaydi, lekin u ikki tugmani turli "og'irlikdagi"
    elementga aylantiradi va kichik modalda bu ortiqcha shovqin:
    ikkalasi ham operator bosishi mumkin bo'lgan teng amallar.

    `tone`:
        neutral - ikkilamchi/xavfli amal (chiqish); hover'da qizaradi;
        primary - asosiy amal (qayta urinish), yashil urg'u bilan.
    """
    tones = {
        "neutral": (
            COLORS["text_secondary"],       # matn
            COLORS["border_strong"],        # ramka
            COLORS["error_soft"],           # hover foni
            COLORS["error"],                # hover matni va ramkasi
        ),
        "primary": (
            COLORS["primary_dark"],
            COLORS["primary"],
            COLORS["primary_soft"],
            COLORS["primary_dark"],
        ),
    }
    text, border, hover_bg, hover_fg = tones.get(tone, tones["neutral"])
    return """
        QPushButton {{
            background-color: {surface};
            color: {text};
            border: 1.5px solid {border};
            border-radius: {radius}px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.2px;
            padding: 0 18px;
            min-height: {height}px;
        }}
        QPushButton:hover {{
            background-color: {hover_bg};
            border-color: {hover_fg};
            color: {hover_fg};
        }}
        QPushButton:pressed {{
            background-color: {hover_fg};
            border-color: {hover_fg};
            color: {on_primary};
        }}
        QPushButton:disabled {{
            background-color: {surface_alt};
            border-color: {border_soft};
            color: {text_muted};
        }}
    """.format(
        radius=height // 2,
        height=height,
        text=text,
        border=border,
        hover_bg=hover_bg,
        hover_fg=hover_fg,
        surface=COLORS["surface"],
        surface_alt=COLORS["surface_alt"],
        border_soft=COLORS["border"],
        text_muted=COLORS["text_muted"],
        on_primary=COLORS["on_primary"],
    )


def info_field_style() -> str:
    """
    MD3 "outlined container" - o'qish uchun mo'ljallangan qiymat bloki.

    Tugma emas, forma maydoni ham emas: operator undan raqamni
    KO'CHIRIB oladi (administratorga aytish uchun), shuning uchun u
    ajralib turishi, lekin bosiladigandek ko'rinmasligi kerak.
    """
    # Selektor obyekt NOMI bo'yicha, `QFrame` bo'yicha EMAS: `QLabel`
    # ham `QFrame` merosxo'ri, shuning uchun oddiy `QFrame {...}`
    # uslubi konteyner ichidagi har bir matnga ham ramka va fon
    # chizib qo'yadi.
    return """
        QFrame#infoField {{
            background-color: {surface_alt};
            border: 1px solid {border};
            border-radius: 16px;
        }}
    """.format(**COLORS)


def badge_style(kind: str = "success") -> str:
    """Kichik holat yorlig'i (chip)."""
    mapping = {
        "success": (COLORS["success_soft"], COLORS["primary_dark"]),
        "error": (COLORS["error_soft"], COLORS["error"]),
        "warning": (COLORS["warning_soft"], COLORS["warning"]),
        "info": (COLORS["info_soft"], "#0369A1"),
        "muted": (COLORS["surface_alt"], COLORS["text_secondary"]),
    }
    background, color = mapping.get(kind, mapping["muted"])
    return """
        background-color: {bg};
        color: {fg};
        border-radius: 11px;
        padding: 4px 12px;
        font-size: 13px;
        font-weight: 600;
    """.format(bg=background, fg=color)


def message_style(kind: str = "error") -> str:
    """Forma ostidagi xabar qatori."""
    mapping = {
        "error": (COLORS["error_soft"], COLORS["error"], "#FCA5A5"),
        "success": (COLORS["success_soft"], COLORS["primary_dark"], "#86EFAC"),
        "warning": (COLORS["warning_soft"], COLORS["warning"], "#FCD34D"),
        "info": (COLORS["info_soft"], "#0369A1", "#7DD3FC"),
    }
    background, color, border = mapping.get(kind, mapping["error"])
    return """
        background-color: {bg};
        color: {fg};
        border: 1px solid {bd};
        border-radius: 12px;
        padding: 11px 16px;
        font-size: 14px;
        font-weight: 600;
    """.format(bg=background, fg=color, bd=border)
