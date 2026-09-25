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
    """
    Material Design 3 "filled button" — asosiy amal.

    GRADIENT YO'Q va bu ataylab. Ilgari tugma to'q yashildan
    yashilga o'tuvchi gradient edi va u ikki narsani buzardi:

      * MD3 da to'ldirilgan tugma BITTA rang bo'ladi, holat esa
        ustiga qo'yiladigan "state layer" bilan ko'rsatiladi.
        Gradient o'sha qatlamni ko'rinmas qilardi — hover'da
        tugma o'zgargani sezilmasdi;
      * chap cheti `primary_dark` bo'lgani uchun tugma umuman
        to'qroq ko'rinardi va yonidagi yashil nishonlar
        (`badge_style("success")`) bilan bir oilaga o'xshamasdi.

    Endi holatlar MD3 tartibida: tinch — `primary`, hover — bir
    pog'ona yorug' (`primary_light`, ya'ni ustiga qo'yilgan oq
    state layer effekti), bosilganda — to'q (`primary_dark`).

    Burchak radiusi BALANDLIKNING YARMI: MD3 to'ldirilgan tugmasi
    "pill" shaklida va bu uni oyna ichidagi to'rtburchak
    kartalardan ajratib turadi — ko'z bosiladigan elementni
    shakli bo'yicha topadi.
    """
    return """
        QPushButton {{
            background-color: {primary};
            color: {on_primary};
            border: none;
            border-radius: {radius}px;
            padding: 0 24px;
            font-size: 15px;
            font-weight: 700;
            letter-spacing: 0.4px;
            min-height: {height}px;
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


def tonal_button_style(height: int = 44) -> str:
    """
    Material Design 3 "filled tonal" tugmasi.

    Uchinchi og'irlik darajasi: to'ldirilgan (asosiy amal) va
    chizilgan (ikkilamchi) orasida. Aynan shu daraja kerak bo'ladigan
    joy — sahifadagi YORDAMCHI, lekin tez-tez bosiladigan amal
    ("Kamerani ishga tushirish"): u asosiy amal ("Davom etish") bilan
    raqobatlashmasligi, lekin ko'zdan ham qochmasligi kerak.
    """
    return """
        QPushButton {{
            background-color: {primary_soft};
            color: {primary_deep};
            border: none;
            border-radius: {radius}px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.2px;
            padding: 0 22px;
            min-height: {height}px;
        }}
        QPushButton:hover {{
            background-color: #BBF7D0;
        }}
        QPushButton:pressed {{
            background-color: {primary};
            color: {on_primary};
        }}
        QPushButton:disabled {{
            background-color: {surface_alt};
            color: {text_muted};
        }}
    """.format(radius=height // 2, height=height, **COLORS)


def danger_button_style(height: int = 48) -> str:
    """
    MD3 "filled" tugma — QAYTARIB BO'LMAYDIGAN amal uchun (xato rangi).

    Faqat tasdiqlash dialogida va faqat bitta: "Imtihonni yakunlash"
    talabgorning testga qaytish yo'lini yopadi. Qizil to'ldirilgan
    tugma boshqa hech qayerda ishlatilmaydi — aks holda u "bu yerda
    ehtiyot bo'ling" degan signal bo'lishdan to'xtaydi.
    """
    return """
        QPushButton {{
            background-color: {error};
            color: {on_primary};
            border: none;
            border-radius: {radius}px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.3px;
            padding: 0 22px;
            min-height: {height}px;
        }}
        QPushButton:hover {{
            background-color: #EF4444;
        }}
        QPushButton:pressed {{
            background-color: #B91C1C;
        }}
        QPushButton:disabled {{
            background-color: {error_soft};
            color: {surface};
        }}
    """.format(radius=height // 2, height=height, **COLORS)


def text_button_style(height: int = 34) -> str:
    """
    MD3 "text button" — karta sarlavhasi yonidagi yordamchi amal.

    IKONKA EMAS, MATN. Ikonka tugmasi bu yerda chiroyliroq ko'rinardi,
    lekin loyihada ikonka resurslari yo'q va Unicode belgisi (⟳)
    Windows'ning barcha shrift to'plamlarida mavjud emas — belgi
    topilmasa tugma BO'SH KVADRAT bo'lib chiqadi. Operator uchun bu
    "bosiladigan narsami yoki nosozlikmi?" degan savol, ya'ni eng
    yomon holat. Matn har doim chiziladi.
    """
    return """
        QPushButton {{
            background-color: transparent;
            color: {primary_dark};
            border: none;
            border-radius: {radius}px;
            padding: 0 14px;
            font-size: 13px;
            font-weight: 700;
            min-height: {height}px;
        }}
        QPushButton:hover {{
            background-color: {primary_soft};
        }}
        QPushButton:pressed {{
            background-color: {primary};
            color: {on_primary};
        }}
        QPushButton:disabled {{
            color: {text_muted};
            background-color: transparent;
        }}
    """.format(radius=height // 2, height=height, **COLORS)


def chip_style(selected: bool = False, tone: str = "primary") -> str:
    """
    MD3 "filter chip" — oldindan ko'rish uchun kamerani tanlash.

    Tanlangan holat RANG BILAN CHEKLANMAYDI: ramka qalinligi va fon
    birga o'zgaradi. Rang ajratolmaydigan operator uchun faqat rang
    farqi ma'lumotni yo'qotadi, chegara esa qoladi.
    """
    palette = {
        "primary": (COLORS["primary_soft"], COLORS["primary_deep"], COLORS["primary"]),
        "neutral": (COLORS["surface_alt"], COLORS["text"], COLORS["border_strong"]),
    }
    fill, fg, edge = palette.get(tone, palette["primary"])
    if selected:
        return """
            QPushButton {{
                background-color: {fill};
                color: {fg};
                border: 1.5px solid {edge};
                border-radius: 16px;
                padding: 0 16px;
                min-height: 32px;
                font-size: 13px;
                font-weight: 700;
            }}
        """.format(fill=fill, fg=fg, edge=edge)
    return """
        QPushButton {{
            background-color: transparent;
            color: {text_secondary};
            border: 1px solid {border};
            border-radius: 16px;
            padding: 0 16px;
            min-height: 32px;
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {surface_alt};
            color: {text};
        }}
    """.format(**COLORS)


def segmented_button_style(*, selected: bool, position: str = "left") -> str:
    """
    Material Design 3 "segmented button" — bir-biriga ULANGAN tanlov.

    NIMA UCHUN CHIP EMAS. Chip mustaqil filtr ("shu belgini yoq/o'chir"),
    segment esa BIR TO'PLAMDAN BITTASINI tanlash: kamera yoki yuz
    tekshiruvida, yoki obyekt aniqlashda bo'ladi - ikkalasida ham
    emas, hech qaysisida ham emas. Ulangan ko'rinish aynan shu
    "bittasi" ma'nosini beradi, ajratilgan chiplar esa "ikkalasini
    ham belgilash mumkin" degan taassurot qoldirardi.

    TANLANGAN HOLAT RANG BILAN CHEKLANMAYDI: fon, matn qalinligi va
    belgi (✓) birga o'zgaradi. Rang ajratolmaydigan operator uchun
    faqat rang farqi ma'lumotni yo'qotardi (`chip_style` bilan bir
    xil qoida).

    `position` — segmentning to'plamdagi o'rni: tashqi burchaklar
    yumaloq, ichkilari to'g'ri. Oraliqdagi CHEGARA BITTA: chapdagi
    segmentning o'ng ramkasi olib tashlanadi, aks holda ikkita 1px
    ramka yonma-yon tushib, ajratuvchi chiziq ikki barobar
    qalinlashardi.
    """
    outer = 18
    left_radius = outer if position in ("left", "single") else 0
    right_radius = outer if position in ("right", "single") else 0
    # Oxirgi segmentdan boshqasida o'ng ramka YO'Q: ajratuvchi
    # chiziqni keyingi segmentning chap ramkasi beradi.
    right_border = "none" if position in ("left", "middle") else "1px solid {}".format(
        COLORS["border_strong"] if selected else COLORS["border"]
    )

    if selected:
        return """
            QPushButton {{
                background-color: {fill};
                color: {fg};
                border: 1px solid {edge};
                border-right: {right_border};
                border-top-left-radius: {left_radius}px;
                border-bottom-left-radius: {left_radius}px;
                border-top-right-radius: {right_radius}px;
                border-bottom-right-radius: {right_radius}px;
                padding: 0 12px;
                min-height: 34px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:disabled {{
                color: {text_muted};
            }}
        """.format(
            fill=COLORS["primary_soft"],
            fg=COLORS["primary_deep"],
            edge=COLORS["border_strong"],
            right_border=right_border,
            left_radius=left_radius,
            right_radius=right_radius,
            text_muted=COLORS["text_muted"],
        )

    return """
        QPushButton {{
            background-color: transparent;
            color: {text_secondary};
            border: 1px solid {border};
            border-right: {right_border};
            border-top-left-radius: {left_radius}px;
            border-bottom-left-radius: {left_radius}px;
            border-top-right-radius: {right_radius}px;
            border-bottom-right-radius: {right_radius}px;
            padding: 0 12px;
            min-height: 34px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {surface_alt};
            color: {text};
        }}
        QPushButton:disabled {{
            color: {text_muted};
        }}
    """.format(
        right_border=right_border,
        left_radius=left_radius,
        right_radius=right_radius,
        **COLORS
    )


def surface_container_style(object_name: str, *, tone: str = "low") -> str:
    """
    MD3 "surface container" — kartaning ichidagi ajratilgan blok.

    Selektor obyekt NOMI bo'yicha (`QFrame` bo'yicha emas): `QLabel`
    ham `QFrame` merosxo'ri va oddiy `QFrame {...}` uslubi konteyner
    ichidagi har bir matnga ramka chizib qo'yadi
    (`info_field_style` dagi bilan bir xil tuzoq).
    """
    tones = {
        "low": (COLORS["surface_alt"], COLORS["border"]),
        "high": (COLORS["primary_soft"], "#BBF7D0"),
        "error": (COLORS["error_soft"], "#FCA5A5"),
    }
    background, border = tones.get(tone, tones["low"])
    return """
        QFrame#{name} {{
            background-color: {bg};
            border: 1px solid {bd};
            border-radius: 16px;
        }}
    """.format(name=object_name, bg=background, bd=border)


def preview_surface_style() -> str:
    """Video oldindan ko'rish maydoni — MD3 "surface dim" ustida."""
    return """
        background-color: #0B1220;
        border-radius: 20px;
        color: {text_muted};
        font-size: 13px;
    """.format(**COLORS)


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


def code_field_style(height: int = 64) -> str:
    """
    MD3 "filled text field" — qat'iy uzunlikdagi raqam uchun.

    Oddiy `QLineEdit` dan uch narsa bilan farq qiladi va uchalasi
    ham JSHSHIR kiritish holatidan kelib chiqqan:

      * raqamlar MARKAZDA va oralig'i keng — 14 xonali sonni
        ko'z bilan tekshirish (hujjatdagi bilan solishtirish)
        chapga tekislangan zich matnda deyarli imkonsiz;
      * balandlik katta — operator uni yarim qarab, klaviaturaga
        qaramasdan to'ldiradi;
      * fokus ramkasi qalinroq (2 px) va fon oqaradi — maydon
        ekranning markazida turadi va operator unga to'liq
        qaramasdan yozadi.

    "TO'LDIRILDI" HOLATI RANG BILAN KO'RSATILMAYDI. Ramka fokus
    paytida allaqachon yashil (MD3 standarti), ya'ni yozib
    turgan operator uchun ikkinchi yashil hech qanday yangi
    ma'lumot bermasdi - u faqat "fokus" va "to'ldirildi"
    signallarini bir-biriga aralashtirardi. O'sha holat MATNDA
    ko'rsatiladi: hisoblagich ("7 / 14") va yordamchi qator
    ("Yana 7 ta raqam" -> "Tayyor").
    """
    return """
        QLineEdit {{
            background-color: {surface_alt};
            border: 1.5px solid {border};
            border-radius: 18px;
            padding: 0 18px;
            min-height: {height}px;
            font-size: 26px;
            font-weight: 600;
            letter-spacing: 6px;
            color: {text};
            selection-background-color: {primary_light};
        }}
        QLineEdit:hover {{
            border-color: {border_strong};
        }}
        QLineEdit:focus {{
            background-color: {surface};
            border: 2px solid {primary};
        }}
    """.format(height=height, **COLORS)


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
