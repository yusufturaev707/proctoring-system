"""
Dizayn tizimi - Material Design 3, yashil brend urg'usi bilan.

Barcha ranglar SHU YERDA. Sahifalarda hex kod yozilmaydi: mavzu
o'zgarsa (masalan boshqa muassasa brendi) o'zgarish bitta faylda qoladi.

MD3 qoidalari (butun client bo'ylab):
  * shakl: maydon 12 px, karta 16-22 px, dialog 28 px, tugma "pill";
  * ajratish TON bilan (sirt konteynerlari), ramka bilan emas;
  * holat - "state layer": hover yorug'roq, bosilgan to'qroq; nofaol -
    `disabled_container` / `disabled_content`;
  * xabar bloklari - `*_container` fon + `on_*_container` matn, ramkasiz.
"""

# ---------------------------------------------------------------------
# Palitra
#
# Yashil - tizimning asosiy rangi: "ruxsat berildi / tayyor" holati
# proktorlikdagi eng ko'p uchraydigan ijobiy signal. Qizil FAQAT
# haqiqiy to'siq uchun ishlatiladi, aks holda u ko'zga tashlanmay
# qoladi.
# ---------------------------------------------------------------------
#
# MATERIAL DESIGN 3 TONAL ROLLARI. Brend rangi (`primary`) o'zgarmadi -
# qolganlari undan hosil qilingan MD3 tonal palitrasi: sirtlar yashilga
# ozgina moyil ("tinted surface"), ajratish RAMKA bilan emas, TON bilan.
# Ilgari har karta, xabar va blok 1 px kulrang ramkali edi va ekran
# "jadval katakchalari" dek ko'rinardi; MD3 da ramka faqat maydon
# (outlined text field) va outlined tugmada qoladi.
#
# Eski kalitlar (`primary_soft`, `surface_alt`, `border` ...) SAQLANADI -
# ular 180 dan ortiq joyda ishlatiladi; qiymatlari mos MD3 roliga
# tenglashtirilgan. Yangi kod MD3 nomlarini ishlatadi.
# ---------------------------------------------------------------------
_MD3 = {
    # Primary (brend yashili) - asosiy amal, fokus, tanlangan holat.
    "primary": "#16A34A",
    "on_primary": "#FFFFFF",
    "primary_container": "#C8F1D3",
    "on_primary_container": "#00391B",
    # Secondary - neytral-yashil tonal elementlar (filter chip, tonal tugma).
    "secondary_container": "#D5E8D6",
    "on_secondary_container": "#101F13",
    # Tertiary - ma'lumot (info) urg'usi.
    "tertiary": "#0E6A7A",
    "tertiary_container": "#C6EBF2",
    "on_tertiary_container": "#001F25",
    # Error.
    "error": "#BA1A1A",
    "error_container": "#FFDAD6",
    "on_error_container": "#93000A",
    # Warning - MD3 da yo'q, xuddi shu qoida bilan qo'shilgan.
    "warning": "#B45309",
    "warning_container": "#FFE2BF",
    "on_warning_container": "#5C2B00",
    # Sirtlar: fon -> konteynerlar (pastdan yuqoriga to'qlashadi).
    "surface_bright": "#F6FAF5",
    "surface_container_lowest": "#FFFFFF",
    "surface_container_low": "#F0F5EF",
    "surface_container": "#EAF0E9",
    "surface_container_high": "#E4EAE3",
    "surface_container_highest": "#DEE4DD",
    "on_surface": "#171D19",
    "on_surface_variant": "#414941",
    "outline": "#717970",
    "outline_variant": "#C1C9BF",
    "inverse_surface": "#2C322D",
    "inverse_on_surface": "#EDF2EB",
}

COLORS = {
    **_MD3,
    # --- eski nomlar -> MD3 rollari ---------------------------------
    # Hover: primary ustiga 8% oq "state layer"; bosilgan: to'q ton.
    "primary_light": "#2EAD5B",
    "primary_dark": "#15803D",
    "primary_deep": _MD3["on_primary_container"],
    "primary_soft": _MD3["primary_container"],
    "accent": _MD3["tertiary"],
    "background": _MD3["surface_bright"],
    "surface": _MD3["surface_container_lowest"],
    "surface_alt": _MD3["surface_container_low"],
    "border": "#DCE3DA",
    "border_strong": _MD3["outline_variant"],
    "text": _MD3["on_surface"],
    "text_secondary": _MD3["on_surface_variant"],
    "text_muted": _MD3["outline"],
    "error_soft": _MD3["error_container"],
    "warning_soft": _MD3["warning_container"],
    "success": _MD3["primary"],
    "success_soft": _MD3["primary_container"],
    "info_soft": _MD3["tertiary_container"],
    # MD3 nofaol holat: `on_surface` ning 12% (fon) va 38% (matn) i -
    # oq sirt ustida hisoblangan tayyor qiymat (Qt uslubida rgba bilan
    # aralashtirish har vidjetning ota fonga bog'liq bo'lib qolardi).
    "disabled_container": "#E1E4E0",
    "disabled_content": "#9FA49E",
}

FONT_FAMILY = "'Segoe UI', 'Inter', 'Roboto', sans-serif"

#: MD3 shakl shkalasi: "medium" (maydon, ro'yxat) va "large" (karta).
RADIUS = 12
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

/* Karta - sahifa fonidan TON bilan ajraladi; ingichka ramka faqat
   yorug' monitorlarda chegarani saqlash uchun (outline_variant'dan och). */
QFrame[role="card"] {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: {radius_lg}px;
}}
QFrame[role="panel"] {{
    background-color: {surface_container_low};
    border: none;
    border-radius: 16px;
}}
QFrame[role="divider"] {{
    background-color: {border};
    max-height: 1px;
    border: none;
}}

/* MD3 filled button (standart tugma). */
QPushButton {{
    background-color: {primary};
    color: {on_primary};
    border: none;
    border-radius: 22px;
    padding: 12px 24px;
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
    background-color: {disabled_container};
    color: {disabled_content};
}}

/* MD3 outlined button. */
QPushButton[variant="ghost"] {{
    background-color: transparent;
    color: {primary_dark};
    border: 1px solid {outline};
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {surface_container_low};
}}
QPushButton[variant="ghost"]:pressed {{
    background-color: {surface_container};
}}
QPushButton[variant="danger"] {{
    background-color: {error};
}}
QPushButton[variant="danger"]:hover {{
    background-color: #C73A36;
}}
/* MD3 text button. */
QPushButton[variant="link"] {{
    background: transparent;
    color: {primary_dark};
    border: none;
    border-radius: 16px;
    padding: 6px 12px;
    min-height: 28px;
    font-weight: 600;
}}
QPushButton[variant="link"]:hover {{
    background-color: {primary_container};
}}

/* MD3 outlined text field: 1 px outline_variant, fokusda 2 px primary. */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {surface};
    border: 1px solid {outline_variant};
    border-radius: {radius}px;
    padding: 12px 16px;
    font-size: 15px;
    selection-background-color: {primary_container};
    selection-color: {on_primary_container};
}}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: {outline};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {primary};
    padding: 11px 15px;
}}
QLineEdit:disabled {{
    background-color: {surface_container_low};
    color: {disabled_content};
    border-color: {border};
}}

QComboBox {{
    background-color: {surface};
    border: 1px solid {outline_variant};
    border-radius: {radius}px;
    padding: 11px 16px;
    font-size: 15px;
    min-height: 44px;
}}
QComboBox:hover {{
    border-color: {outline};
}}
QComboBox:focus, QComboBox:on {{
    border: 2px solid {primary};
    padding: 10px 15px;
}}
QComboBox:disabled {{
    background-color: {surface_container_low};
    color: {disabled_content};
    border-color: {border};
}}
QComboBox::drop-down {{
    border: none;
    width: 34px;
}}
/* MD3 menu: surface_container, 12 px, tanlangan qator - secondary_container. */
QComboBox QAbstractItemView {{
    background-color: {surface_container_low};
    border: none;
    border-radius: 12px;
    padding: 8px 0;
    selection-background-color: {secondary_container};
    selection-color: {on_secondary_container};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 44px;
    padding: 0 16px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {surface_container_high};
}}

/* MD3 linear progress indicator: 4 px, trek - primary_container. */
QProgressBar {{
    border: none;
    border-radius: 2px;
    background-color: {primary_container};
    max-height: 4px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {primary};
    border-radius: 2px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {outline_variant};
    border-radius: 3px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{
    background: {outline};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}

/* MD3 plain tooltip: inverse_surface, 4 px. */
QToolTip {{
    background-color: {inverse_surface};
    color: {inverse_on_surface};
    border: none;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 13px;
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
            background-color: {disabled_container};
            color: {disabled_content};
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
            COLORS["on_surface_variant"],   # matn
            COLORS["outline"],              # ramka (MD3 outlined: `outline`)
            COLORS["error_container"],      # hover foni
            COLORS["error"],                # hover matni va ramkasi
        ),
        "primary": (
            COLORS["primary_dark"],
            COLORS["outline"],
            COLORS["primary_container"],
            COLORS["primary_dark"],
        ),
    }
    text, border, hover_bg, hover_fg = tones.get(tone, tones["neutral"])
    return """
        QPushButton {{
            background-color: {surface};
            color: {text};
            border: 1px solid {border};
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
            background-color: transparent;
            border-color: {disabled_container};
            color: {disabled_content};
        }}
    """.format(
        radius=height // 2,
        height=height,
        text=text,
        border=border,
        hover_bg=hover_bg,
        hover_fg=hover_fg,
        surface=COLORS["surface"],
        disabled_container=COLORS["disabled_container"],
        disabled_content=COLORS["disabled_content"],
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
            background-color: {secondary_container};
            color: {on_secondary_container};
            border: none;
            border-radius: {radius}px;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.2px;
            padding: 0 22px;
            min-height: {height}px;
        }}
        QPushButton:hover {{
            background-color: {primary_container};
            color: {on_primary_container};
        }}
        QPushButton:pressed {{
            background-color: #B2E4BF;
            color: {on_primary_container};
        }}
        QPushButton:disabled {{
            background-color: {disabled_container};
            color: {disabled_content};
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
            background-color: #C73A36;
        }}
        QPushButton:pressed {{
            background-color: #93000A;
        }}
        QPushButton:disabled {{
            background-color: {disabled_container};
            color: {disabled_content};
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
            background-color: {primary_container};
        }}
        QPushButton:pressed {{
            background-color: #B2E4BF;
        }}
        QPushButton:disabled {{
            color: {disabled_content};
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
        "primary": (COLORS["secondary_container"], COLORS["on_secondary_container"], COLORS["secondary_container"]),
        "neutral": (COLORS["surface_container_high"], COLORS["text"], COLORS["surface_container_high"]),
    }
    fill, fg, edge = palette.get(tone, palette["primary"])
    if selected:
        return """
            QPushButton {{
                background-color: {fill};
                color: {fg};
                border: 1px solid {edge};
                border-radius: 8px;
                padding: 0 16px;
                min-height: 32px;
                font-size: 13px;
                font-weight: 700;
            }}
        """.format(fill=fill, fg=fg, edge=edge)
    return """
        QPushButton {{
            background-color: transparent;
            color: {on_surface_variant};
            border: 1px solid {outline_variant};
            border-radius: 8px;
            padding: 0 16px;
            min-height: 32px;
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {surface_container_low};
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
            fill=COLORS["secondary_container"],
            fg=COLORS["on_secondary_container"],
            edge=COLORS["outline"],
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
    # RAMKASIZ: MD3 da konteyner sirtdan TON bilan ajraladi. Ilgari har
    # blok ramkali edi va dialog ichida uchta ichma-ich chegara hosil
    # bo'lardi (karta -> blok -> maydon).
    tones = {
        "low": COLORS["surface_container_low"],
        "high": COLORS["primary_container"],
        "error": COLORS["error_container"],
        "warning": COLORS["warning_container"],
    }
    background = tones.get(tone, tones["low"])
    return """
        QFrame#{name} {{
            background-color: {bg};
            border: none;
            border-radius: 16px;
        }}
    """.format(name=object_name, bg=background)


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
            background-color: {surface_container_low};
            border: none;
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
            background-color: {surface_container_low};
            border: 1px solid {outline_variant};
            border-radius: 18px;
            padding: 0 18px;
            min-height: {height}px;
            font-size: 26px;
            font-weight: 600;
            letter-spacing: 6px;
            color: {text};
            selection-background-color: {primary_container};
            selection-color: {on_primary_container};
        }}
        QLineEdit:hover {{
            border-color: {outline};
        }}
        QLineEdit:focus {{
            background-color: {surface};
            border: 2px solid {primary};
        }}
    """.format(height=height, **COLORS)


def badge_style(kind: str = "success") -> str:
    """Kichik holat yorlig'i (chip)."""
    mapping = {
        "success": (COLORS["primary_container"], COLORS["on_primary_container"]),
        "error": (COLORS["error_container"], COLORS["on_error_container"]),
        "warning": (COLORS["warning_container"], COLORS["on_warning_container"]),
        "info": (COLORS["tertiary_container"], COLORS["on_tertiary_container"]),
        "muted": (COLORS["surface_container_high"], COLORS["on_surface_variant"]),
    }
    background, color = mapping.get(kind, mapping["muted"])
    return """
        background-color: {bg};
        color: {fg};
        border-radius: 8px;
        padding: 4px 12px;
        font-size: 13px;
        font-weight: 600;
    """.format(bg=background, fg=color)


def message_style(kind: str = "error") -> str:
    """Forma ostidagi xabar qatori."""
    mapping = {
        "error": (COLORS["error_container"], COLORS["on_error_container"]),
        "success": (COLORS["primary_container"], COLORS["on_primary_container"]),
        "warning": (COLORS["warning_container"], COLORS["on_warning_container"]),
        "info": (COLORS["tertiary_container"], COLORS["on_tertiary_container"]),
    }
    background, color = mapping.get(kind, mapping["error"])
    return """
        background-color: {bg};
        color: {fg};
        border: none;
        border-radius: 12px;
        padding: 12px 16px;
        font-size: 14px;
        font-weight: 600;
    """.format(bg=background, fg=color)
