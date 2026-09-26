"""
Kamera rollarini aniqlash: qaysi kamera nima uchun ishlatiladi.

QOIDA BITTA VA U CLIENTDA. Ilgari birinchi manba server biriktirishi
edi (`CameraAssignment`): administrator har bir kompyuter uchun
qaysi kamera qaysi rolda ishlashini panelda yozardi. U olib
tashlandi va sabab amaliyotda ko'rindi — 500 mashinani qo'lda
biriktirib chiqish kunlab vaqt oladi, ya'ni jadval deyarli har
doim bo'sh qolardi va client baribir shu yerdagi zaxira qoidaga
tushardi. Rolni esa operator BIR BOSISHDA tuzatadi: u ikkala
kadrni ekranda ko'rib turibdi, administrator jadvalda faqat nomni
ko'radi.

TAXMIN QOIDASI:

    birinchi kamera  -> YUZ TEKSHIRUVI   (primary)
    ikkinchi kamera  -> OBYEKT ANIQLASH  (secondary)

Tartib esa: avval lokal veb-kameralar, keyin IP kameralar. Bu ataylab
teskari ko'rinishi mumkin — IP kamera "jiddiyroq" uskuna — lekin
FIZIKA shuni aytadi:

  * veb-kamera monitorga o'rnatilgan va talabgorning YUZIGA qaraydi;
  * IP kamera (`Camera` modeli izohi: "Zonani kuzatadi") shiftga yoki
    burchakka o'rnatilgan va XONANI ko'radi.

Ya'ni aralash o'rnatishda (veb-kamera + IP kamera) to'g'ri taqsimot
o'z-o'zidan chiqadi: yuz — veb-kameradan, obyektlar va ikkinchi odam —
IP kameradan. Faqat IP kamera bo'lsa, u birinchi bo'lib qoladi va yuz
tekshiruvini o'z zimmasiga oladi — bu qoidaning istisnosi emas,
davomi.

ROLLARNI ALMASHTIRISH tahlilni JIMGINA buzadi: yuz modeli stol
ustidan yuz qidiradi, obyekt modeli yuz kadridan telefon — ikkalasi
ham "hech narsa topilmadi" deb xabar beradi. Shuning uchun taxmin
operatordan YASHIRILMAYDI: panel uni ochiq yozadi va har kadr
ustida vazifani tanlash turadi (`reassign`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

#: Rol -> vazifa. Ikkitadan ortiq rol yo'q va bo'lishi ham kerak emas:
#: "yana bitta kamera" o'z-o'zicha hech narsa bermaydi, uning VAZIFASI
#: aniqlanishi kerak.
ROLE_PURPOSE = {
    "primary": "face",
    "secondary": "objects",
}

PURPOSE_LABEL = {
    "face": "Yuz tekshiruvi",
    "objects": "Obyekt aniqlash",
    "spare": "Ishlatilmaydi",
}

#: Vazifa -> rol. `spare` - rolsiz qurilma: ro'yxatda va oldindan
#: ko'rishda bor, imtihon kuzatuvida esa ISHTIROK ETMAYDI.
PURPOSE_ROLE = {"face": "primary", "objects": "secondary", "spare": ""}

ROLE_ORDER = ("primary", "secondary")


@dataclass
class ResolvedCamera:
    """Bitta rolga tayinlangan kamera va uning ishlatilishga yaroqliligi."""

    role: str
    source: str = "local"                 # local | ip
    label: str = ""
    local_index: Optional[int] = None
    #: Lokal kameraning BARQAROR identifikatori (DirectShow
    #: `DevicePath`). Indeks qurilmalar qayta sanalganda siljishi
    #: mumkin, bu esa yo'q - operator tanlovi shunga bog'lanadi.
    device_path: str = ""
    address: str = ""
    transport: str = "tcp"
    #: IP kameraning serverdagi identifikatori (kredensial shu
    #: bo'yicha so'raladi - `CameraSpec.camera_id` izohiga qarang).
    camera_id: Optional[int] = None
    #: Serverdan kelgan ro'yxatda bormi. IP kamera uchun bu HAL
    #: QILUVCHI: kredensial faqat server bilgan kameraga beriladi.
    assigned: bool = False
    #: Siyosat bo'yicha majburiymi.
    required: bool = False
    #: Hozir kadr olish mumkinmi.
    available: bool = False
    #: Rol qayerdan keldi / nega ishlatib bo'lmaydi — operator uchun.
    reason: str = ""
    is_virtual: bool = False
    width: int = 0
    height: int = 0

    @property
    def key(self) -> str:
        """
        Kamerani belgilovchi BARQAROR kalit.

        Rol emas: rol o'zgarishi mumkin (operator almashtiradi), kalit
        esa qurilmaning o'ziga tegishli.

        LOKAL KAMERADA AVVAL `DevicePath`. Indeks ham noyob, lekin u
        SANOQDAGI o'rin: bitta kamera uzilsa yoki yangisi ulansa
        qolganlarining indeksi siljiydi va "Yangilash" dan keyin
        operator tanlovi boshqa qurilmaga yopishib qolardi.
        `DevicePath` esa USB VID/PID va port instansiyasidan iborat —
        u siljimaydi. Nom oxirgi zaxira: bir xil modeldagi ikkita
        kamera bir xil nom beradi, shuning uchun u faqat ikkalasi ham
        bo'lmaganda ishlatiladi.
        """
        if self.source == "ip":
            return "ip:{}".format(self.address or self.label)
        if self.device_path:
            return "dev:{}".format(self.device_path)
        if self.local_index is not None:
            return "local:{}".format(self.local_index)
        return "local:{}".format(self.label)

    @property
    def purpose(self) -> str:
        return ROLE_PURPOSE.get(self.role, "spare")

    @property
    def in_use(self) -> bool:
        """Imtihon kuzatuvida ishtirok etadimi (rol berilgan)."""
        return self.role in ROLE_ORDER

    @property
    def slot_id(self) -> str:
        """
        Oldindan ko'rish slotining nomi (`CameraManager`).

        Rolli kamerada - ROLNING O'ZI (kuzatuv va tekshiruv shu nom
        bilan ishlaydi). Zaxirada - qurilma kaliti bo'yicha: uchinchi
        kamera (masalan binodagi IP kamera) ham ekranda ochilishi va
        operator uni ko'rib turib vazifa berishi uchun.
        """
        return self.role or "spare:{}".format(self.key)

    @property
    def purpose_label(self) -> str:
        return PURPOSE_LABEL[self.purpose]

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width else ""

    def as_slot(self) -> dict:
        """
        `CameraManager.configure()` kutadigan shakl.

        `assigned` bu yerda "manager buni ochishi mumkinmi" degan
        ma'noni oladi: HOZIR ishlashga yaroqlilik. IP kamera uchun bu
        "server ro'yxatida bor" (kredensial shu kamera uchun
        beriladi), lokal kamera uchun esa "qurilma topildi".
        """
        return {
            "assigned": self.available,
            "source": self.source,
            "required": self.required,
            "local_index": self.local_index,
            "note": self.reason,
            # NOM LOKAL KAMERADA HAM BERILADI. Ilgari u faqat IP
            # uchun yozilardi, chunki yagona chaqiruvchi
            # (`CameraManager`) nomni aniqlangan qurilmalar
            # ro'yxatidan olardi. Endi ikkinchi chaqiruvchi ham bor
            # (FaceID sahifasi, `source_for_role`) va uning oldida
            # u ro'yxat yo'q — nomsiz slot ekranda "Veb-kamera #1"
            # bo'lib ko'rinardi, operator esa tekshiruv sahifasida
            # boshqa nom ko'rgan bo'lardi.
            "camera": {
                # ID BERILADI: kredensial so'rovi aynan shu bo'yicha
                # ketadi (`camera/stream/`), rol bo'yicha emas.
                "id": self.camera_id,
                "name": self.label,
                # YO'L HAM BERILADI: qurilmani ochadigan tomon
                # (`camera/factory.py`) indeks siljib ketgan holatni
                # aynan shu bo'yicha tuzatadi - aks holda FaceID
                # sahifasi boshqa kamerani ochib qo'yardi.
                "device_path": self.device_path,
                "ip_address": self.address if self.source == "ip" else "",
                "transport": self.transport,
            },
        }


@dataclass
class CameraLayout:
    """Aniqlangan taqsimot. Sahifalar shundan foydalanadi."""

    cameras: list = field(default_factory=list)
    #: Rollarni OPERATOR tanladimi (`reassign`). Taxmindan farqi:
    #: bunga ishonch bor - odam kameralarni ko'rib turib tanladi.
    chosen_by_operator: bool = False

    @property
    def can_choose(self) -> bool:
        """
        Operator rollarni o'zgartira oladimi.

        Tanlash faqat IKKI VA UNDAN ORTIQ ishlaydigan kamerada
        ma'noga ega: bittasida tanlaydigan narsa yo'q.
        """
        return len(self.usable) >= 2

    def get(self, role: str) -> Optional[ResolvedCamera]:
        return next((item for item in self.cameras if item.role == role), None)

    @property
    def face(self) -> Optional[ResolvedCamera]:
        return self.get("primary")

    @property
    def objects(self) -> Optional[ResolvedCamera]:
        return self.get("secondary")

    @property
    def usable(self) -> list:
        """Ishlaydigan BARCHA qurilmalar - zaxiradagilar ham."""
        return [item for item in self.cameras if item.available]

    @property
    def in_use(self) -> list:
        """
        Imtihonda ISHLATILADIGAN kameralar (rol berilgan va ishlaydi).

        Siyosat tekshiruvlari (virtual kamera, rezolyutsiya) SHULARGA
        qo'llanadi, `usable` ga emas: zaxirada turgan OBS virtual
        kamerasi imtihonni to'smasligi kerak - u hech narsa
        yozmaydi va hech narsani tasdiqlamaydi.
        """
        return [item for item in self.cameras if item.available and item.in_use]

    def as_slots(self) -> dict:
        """Kuzatuv uchun slotlar - FAQAT rolli kameralar."""
        return {item.role: item.as_slot() for item in self.cameras if item.in_use}

    def preview_slots(self) -> dict:
        """Tekshiruv sahifasidagi oldindan ko'rish uchun - HAMMA qurilma."""
        return {item.slot_id: item.as_slot() for item in self.cameras}

    def choices(self) -> dict:
        """`{kalit: vazifa}` - operator tanlovini "Yangilash" dan keyin tiklash uchun."""
        return {item.key: item.purpose for item in self.cameras}


def resolve(
    *,
    handshake_cameras=None,
    discovered=None,
) -> CameraLayout:
    """
    Rollarni aniqlaydi.

    `handshake_cameras` — server bergan IP kameralar ro'yxati
        (kredensialsiz: bino doirasidagi kameralar).
    `discovered` — `discovery.probe()` topgan lokal kameralar.
    """
    return CameraLayout(cameras=_fallback(handshake_cameras or [], discovered or []))


def assign(layout: CameraLayout, *, key: str, purpose: str) -> CameraLayout:
    """
    Operator qurilmaga VAZIFA beradi: yuz / obyekt / ishlatilmaydi.

    ALMASHTIRISH QOIDASI: vazifani olgan qurilma o'zining eski
    vazifasini shu vazifaning oldingi egasiga beradi. Uchta va undan
    ko'p kamerada ham natija oldindan ma'lum: "IP kamerani obyekt
    aniqlashga ber" - obyekt kamerasi zaxiraga tushadi, boshqa hech
    narsa o'zgarmaydi. Ikki kamerada bu oddiy almashtirish.

    YUZ ROLI HECH QACHON BO'SH QOLMAYDI (ishlaydigan kamera bo'lsa):
    usiz shaxs tekshiruvi umuman bajarilmaydi. Yuz kamerasini
    "Ishlatilmaydi" qilish uning o'rniga keyingisini ko'taradi.
    """
    target = PURPOSE_ROLE.get(purpose)
    chosen = next((item for item in layout.cameras if item.key == key), None)
    if chosen is None or target is None or chosen.role == target:
        return layout

    old_role = chosen.role
    roles = {item.key: item.role for item in layout.cameras}
    if target:
        holder = next((item for item in layout.cameras if item.role == target), None)
        if holder is not None:
            roles[holder.key] = old_role
    elif old_role == "primary":
        # Yuz kamerasi zaxiraga ketmoqda - o'rniga avval ZAXIRADAGI
        # kamera (qurilma tartibida: veb-kamera IP dan oldin), u
        # bo'lmasa obyekt kamerasi ko'tariladi. Teskarisi xonani
        # ko'rayotgan IP kamerani yuzga o'tkazib, obyekt aniqlashni
        # bo'sh qoldirardi.
        successor = next(
            (item for item in _by_device(layout.cameras)
             if item.available and not item.in_use and item.key != key),
            None,
        ) or layout.get("secondary")
        if successor is None:
            # Boshqa ishlaydigan kamera yo'q - yuz kamerasini
            # olib tashlash shaxs tekshiruvini o'chirib qo'yardi.
            return layout
        roles[successor.key] = "primary"
    roles[chosen.key] = target
    return _with_roles(layout, roles, operator=True)


def apply_choices(layout: CameraLayout, choices: dict) -> CameraLayout:
    """
    Oldingi operator tanlovini YANGI aniqlangan taqsimotga qo'llaydi.

    "Yangilash" qurilmalarni qaytadan aniqlaydi va zaxira qoida
    rollarni noldan beradi; tanlov esa QURILMAGA (kalitga) tegishli va
    saqlanishi kerak. Endi ulanmagan qurilmaning tanlovi e'tiborsiz
    qoladi. Yuz va obyekt tanlovlari birinchi, "ishlatilmaydi" oxirida
    qo'llanadi - aks holda zaxiraga tushirish oraliq holatda yuz
    rolini boshqa qurilmaga o'tkazib yuborardi.
    """
    if not choices:
        return layout
    known = {item.key for item in layout.cameras}
    order = {"face": 0, "objects": 1, "spare": 2}
    for key, purpose in sorted(choices.items(), key=lambda pair: order.get(pair[1], 3)):
        if key in known:
            layout = assign(layout, key=key, purpose=purpose)
    return layout


def _with_roles(layout: CameraLayout, roles: dict, *, operator: bool) -> CameraLayout:
    cameras = []
    for camera in layout.cameras:
        role = roles.get(camera.key, camera.role)
        if role == camera.role:
            cameras.append(camera)
            continue
        # `replace` - NUSXA: asl obyektlarni o'zgartirish ularni ushlab
        # turgan boshqa joylarni (`AppState.cameras`) jimgina o'zgartirardi.
        cameras.append(
            replace(
                camera,
                role=role,
                reason=(
                    "Operator tanladi: {}".format(
                        PURPOSE_LABEL[ROLE_PURPOSE.get(role, "spare")].lower()
                    )
                    if camera.available
                    else camera.reason
                ),
            )
        )
    return CameraLayout(cameras=cameras, chosen_by_operator=operator or layout.chosen_by_operator)


def _by_device(cameras: list) -> list:
    """Qurilma bo'yicha barqaror tartib: lokal (indeks), keyin IP (manzil)."""
    return sorted(
        cameras,
        key=lambda camera: (
            camera.source != "local",
            camera.local_index if camera.local_index is not None else 99,
            camera.address,
            camera.label,
        ),
    )


def reassign(layout: CameraLayout, *, face_key: str) -> CameraLayout:
    """
    Yuz kamerasini OPERATOR tanlaydi.

    NIMA UCHUN KERAK. Zaxira qoida kameralarni TARTIB bo'yicha
    taqsimlaydi (birinchisi yuzga, ikkinchisi stolga), lekin OS'dagi
    tartib jismoniy joylashuvni bilmaydi: monitorga o'rnatilgan
    kamera 1-indeksda, stolga qaragan USB kamera esa 0-indeksda
    bo'lishi mumkin. O'shanda taxmin TESKARI chiqadi va tahlil
    JIMGINA buziladi - yuz modeli stol ustidan yuz qidiradi, obyekt
    modeli yuz kadridan telefon, ikkalasi ham "hech narsa
    topilmadi" deb xabar beradi.

    Buni faqat odam tuzata oladi: u ikkala kadrni ekranda ko'rib
    turibdi. Shuning uchun bu funksiya bor.

    Tanlangan kamera `primary` ni oladi, qolganlari MAVJUD
    tartibini saqlab qoladi - ya'ni ikki kamerali mashinada bu
    oddiy almashtirish.
    """
    return assign(layout, key=face_key, purpose="face")


# --------------------------------------------------------------------------
def _fallback(handshake_cameras: list, discovered: list) -> list:
    """
    Biriktirish yo'q — tartib bo'yicha taqsimlaymiz.

    Modul izohidagi qoida: avval lokal veb-kameralar (ular yuzga
    qaraydi), keyin IP kameralar (ular xonani ko'radi). Birinchisi
    yuz tekshiruvini, ikkinchisi obyekt aniqlashni oladi.
    """
    candidates: list = []

    # Virtual kameralar ORQAGA suriladi.
    #
    # Virtual qurilma (OBS, ManyCam) — oldindan yozilgan videoni jonli
    # oqim sifatida ko'rsatishning eng oson yo'li. Uni yuz tekshiruvi
    # roliga qo'yish butun shaxs nazoratini bekor qiladi: model
    # yozuvdagi yuzni ko'radi va har safar "mos keldi" deydi.
    #
    # Bu TAQIQ EMAS — taqiq siyosatda (`allow_virtual_camera`) va uni
    # server majburlaydi. Bu yerdagi tartib faqat shuni ta'minlaydi:
    # mashinada haqiqiy kamera bo'lsa, avtomatik taxmin uni tanlaydi.
    # Virtual qurilma esa ro'yxatda ko'rinib turadi va operator uni
    # "virtual kamera" belgisi bilan ko'radi.
    ordered = sorted(discovered, key=lambda item: (item.is_virtual, item.index))

    for found in ordered:
        candidates.append(
            ResolvedCamera(
                role="",
                source="local",
                label=found.label,
                local_index=found.index,
                device_path=getattr(found, "device_path", ""),
                available=True,
                is_virtual=found.is_virtual,
                width=found.width,
                height=found.height,
                reason="Avtomatik aniqlandi",
            )
        )

    for camera in handshake_cameras or []:
        if not camera.get("is_active", True):
            continue
        candidates.append(
            ResolvedCamera(
                role="",
                source="ip",
                label=camera.get("name") or "IP kamera",
                address=camera.get("ip_address") or "",
                transport=camera.get("transport") or "tcp",
                camera_id=camera.get("id"),
                assigned=True,
                # BINODAGI har bir faol kamera ISHLATSA BO'LADI.
                # Ilgari bu yerda `available=False` turardi, chunki
                # kredensial faqat biriktirilgan kameraga berilardi
                # (`CameraAssignment`). Biriktirish olib tashlandi va
                # doira BINO bo'ldi: server shu binodagi har bir
                # kameraning kalitini beradi, ya'ni oldindan ko'rish
                # ham, tekshiruv ham ishlaydi. Haqiqatan ulanadimi -
                # buni faqat oqimni ochib bilish mumkin va u
                # `CameraStream` ning ishi.
                available=True,
                reason="Binodagi IP kamera",
            )
        )

    # HAMMA QURILMA QOLADI. Ilgari faqat birinchi ikkitasi olinardi
    # (`candidates[:2]`) va ikkita veb-kamerali mashinada binodagi IP
    # kamera ro'yxatdan TUSHIB QOLARDI - operator uni ko'rmas, ishga
    # tushira olmas va unga vazifa bera olmasdi. Endi uchinchi va
    # keyingilari ZAXIRA ("Ishlatilmaydi"): ekranda bor, kuzatuvda yo'q.
    result = []
    for index, camera in enumerate(candidates):
        camera.role = ROLE_ORDER[index] if index < len(ROLE_ORDER) else ""
        if camera.available:
            camera.reason = (
                "Avtomatik: {} (biriktirish yo'q)".format(camera.purpose_label.lower())
                if camera.role
                else "Zaxira: vazifa berilmagan"
            )
        result.append(camera)
    return result


def _find_local(index: Optional[int], discovered: list):
    if not discovered:
        return None
    if index is None:
        return discovered[0]
    return next((item for item in discovered if item.index == index), None)
