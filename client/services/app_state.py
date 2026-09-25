"""
Oqim holati - sahifalar orasida uzatiladigan yagona obyekt.

Sahifalar bir-biriga to'g'ridan-to'g'ri murojaat qilmaydi: har biri
signal chiqaradi, `MainWindow` esa holatni shu yerga yozib, keyingi
sahifani sozlaydi. Shu tufayli sahifani alohida sinash mumkin va
"3-sahifa 2-sahifadagi combo'dan qiymat oladi" turidagi bog'lanish
umuman paydo bo'lmaydi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from proctoring.camera.roles import CameraLayout


@dataclass
class Staff:
    """Tizimga kirgan xodim (operator)."""

    id: int = 0
    username: str = ""
    full_name: str = ""
    role_name: str = ""
    permissions: list = field(default_factory=list)
    is_superuser: bool = False
    region_id: Optional[int] = None
    region_name: str = ""
    zone_id: Optional[int] = None

    @classmethod
    def from_api(cls, data: dict) -> "Staff":
        # Maydonlar backend `UserDetailSerializer` bilan bir xil nomlanadi;
        # `permissions` - `role.permissions` dan yig'ilgan kod ro'yxati.
        return cls(
            id=int(data.get("id") or 0),
            username=data.get("username", ""),
            full_name=data.get("full_name") or data.get("username", ""),
            role_name=data.get("role_name") or "",
            permissions=list(data.get("permissions") or []),
            is_superuser=bool(data.get("is_superuser")),
            region_id=data.get("region"),
            region_name=data.get("region_name", ""),
            zone_id=data.get("zone"),
        )

    def can(self, permission: str) -> bool:
        """
        Ruxsat tekshiruvi - FAQAT UI qulayligi uchun.

        Haqiqiy himoya backendda (`HasRolePermission`). Bu yerdagi
        tekshiruv operatorga ishlatib bo'lmaydigan tugmani ko'rsatmaslik
        uchun, himoya sifatida emas.
        """
        return self.is_superuser or permission in self.permissions


@dataclass
class DeviceInfo:
    """Handshake qaytargan qurilma/kompyuter konteksti."""

    device_id: str = ""
    status: str = "unregistered"
    #: Xonadagi TARTIB RAQAMI (serverdagi `Computer.number`).
    #
    # `inventory_code` dan boshqa savolga javob beradi: kod
    # buxgalteriya uchun va stikerning orqasida, raqam esa stolga
    # yozilgan va operator aynan shu bilan ishlaydi
    # ("12-kompyuterga o'ting"). `None` - raqamlanmagan mashina.
    number: Optional[int] = None
    inventory_code: str = ""
    #: Serverda yasalgan nom ("№12 · INV-001") - client uni
    #: O'ZI YASAMAYDI: raqamsiz mashinada "№None" chiqardi va
    #: qoida ikki joyda yashardi.
    computer_label: str = ""
    zone_id: Optional[int] = None
    zone_name: str = ""
    cameras: list = field(default_factory=list)
    #: Server baholagan mashina tekshiruvi (`machine` bloki):
    #: `status`, `allowed`, `message`, `expected_mac`.
    #:
    #: Bo'sh lug'at - eski server yoki handshake bajarilmagan. U
    #: holda tekshiruv O'TKAZILGAN deb hisoblanadi: client tomonda
    #: "javob yo'q = to'siq" qoidasi butun oqimni server
    #: yangilanmaguncha to'xtatardi, holbuki qaror serverniki.
    machine: dict = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def machine_allowed(self) -> bool:
        """Mashina tekshiruvi imtihonni boshlashga ruxsat berdimi."""
        return bool(self.machine.get("allowed", True))

    @property
    def machine_message(self) -> str:
        """Rad etish sababi - SERVER matni (client uni yasamaydi)."""
        return str(self.machine.get("message") or "")

    @property
    def cameras_online(self) -> int:
        return sum(1 for camera in self.cameras if camera.get("status") == "online")


@dataclass
class ExamOption:
    """Handshake ro'yxatidagi bitta imtihon."""

    id: int
    name: str
    exam_type_id: Optional[int] = None
    exam_type_name: str = ""
    schedule_id: Optional[int] = None
    is_open: bool = True

    @classmethod
    def from_api(cls, data: dict) -> "ExamOption":
        return cls(
            id=int(data.get("id") or 0),
            name=data.get("name", ""),
            exam_type_id=data.get("exam_type_id"),
            exam_type_name=data.get("exam_type_name") or "Turi belgilanmagan",
            schedule_id=data.get("schedule_id"),
            is_open=bool(data.get("is_open", True)),
        )


@dataclass
class Candidate:
    """
    Tashqi platformadan kelgan talabgor.

    `photo_base64` - pasport rasmi. U DB'ga yozilmaydi va faqat kirishdagi
    FaceID uchun xotirada turadi: sessiya tugagach `AppState.reset_flow()`
    uni o'chiradi.
    """

    challenge: str = ""
    full_name: str = ""
    last_name: str = ""
    first_name: str = ""
    middle_name: str = ""
    masked_pinfl: str = ""
    external_candidate_id: str = ""
    #: Platformadagi abituriyent identifikatori (`data.abitur_id`).
    abitur_id: str = ""
    photo_base64: str = ""
    photo_url: str = ""
    has_reference_face: bool = False
    platform_status: str = ""
    #: Platformaning O'Z matni ("Testga ruxsat!"). Client uni
    #: o'zgartirmasdan ko'rsatadi: ruxsat qarori ham, sababi ham
    #: platformada va biz uni faqat yetkazamiz.
    platform_message: str = ""
    #: Testga ajratilgan vaqt DAQIQADA (`data.duration_time`).
    #:
    #: Server uni AYNAN shu birlikda yuboradi va formatlashni
    #: clientga qoldiradi: "3 soat" ko'rinishi taqdimot qarori va u
    #: bir joyda (`duration_label`) turishi kerak.
    duration_minutes: int = 0
    schedule: Optional[dict] = None
    #: Kompyuter broni bo'yicha joy (`exams.bookings.computer_payload`):
    #: `number`, `label`, `zone_name`, `region_name`. `None` — bu test
    #: sessiyasida bron yuritilmaydi.
    seat: Optional[dict] = None

    @property
    def display_name(self) -> str:
        """
        Ekranda ko'rsatiladigan nom.

        Platforma F.I.Sh. ni berishi SHART EMAS (javob sxemasi
        ilgari umuman ismsiz edi), shuning uchun nom kelmagan
        holatda niqoblangan JSHSHIR turadi - "-" chiziqcha
        operatorga hech nima aytmasdi va "ma'lumot kelmadi" degan
        noto'g'ri taassurot qoldirardi.
        """
        return self.full_name or self.masked_pinfl or "Talabgor"

    @property
    def duration_label(self) -> str:
        """
        "180" emas, "3 soat" - ekran uchun.

        Daqiqa xom qiymat: uch xonali son ekranda darhol soatga
        aylantirilishi kerak, aks holda uni talabgorning o'zi
        hisoblaydi va xato hisoblaydi. Bo'sh satr - "platforma
        aytmadi": bunday holatda maydon umuman ko'rsatilmaydi
        ("0 daqiqa" yozuvi yolg'on bo'lardi).
        """
        try:
            minutes = int(self.duration_minutes or 0)
        except (TypeError, ValueError):
            return ""
        if minutes <= 0:
            return ""
        hours, rest = divmod(minutes, 60)
        if hours and rest:
            return "{} soat {} daqiqa".format(hours, rest)
        if hours:
            return "{} soat".format(hours)
        return "{} daqiqa".format(rest)

    @classmethod
    def from_api(cls, payload: dict) -> "Candidate":
        data = payload.get("candidate") or {}
        platform = payload.get("platform") or {}
        return cls(
            challenge=payload.get("challenge", ""),
            full_name=data.get("full_name", ""),
            last_name=data.get("last_name", ""),
            first_name=data.get("first_name", ""),
            middle_name=data.get("middle_name", ""),
            masked_pinfl=data.get("masked_pinfl", ""),
            external_candidate_id=data.get("external_candidate_id", ""),
            abitur_id=str(data.get("abitur_id", "") or ""),
            photo_base64=data.get("photo_base64", "") or "",
            photo_url=data.get("photo_url", "") or "",
            has_reference_face=bool(payload.get("has_reference_face")),
            platform_status=platform.get("status", ""),
            platform_message=platform.get("message", ""),
            duration_minutes=int(payload.get("duration_minutes") or 0),
            schedule=payload.get("schedule"),
            seat=payload.get("seat") or None,
        )


@dataclass
class ProctoringSession:
    """FaceID'dan keyin ochilgan sessiya."""

    token: str = ""
    public_id: str = ""
    status: str = ""
    attempt_no: int = 1
    exam_id: int = 0
    exam_name: str = ""
    identity_confirmed: bool = False

    @classmethod
    def from_api(cls, payload: dict) -> "ProctoringSession":
        session = payload.get("session") or {}
        exam = session.get("exam") or {}
        return cls(
            token=payload.get("proctoring_session_token", ""),
            public_id=session.get("public_id", ""),
            status=session.get("status", ""),
            attempt_no=int(session.get("attempt_no") or 1),
            exam_id=int(exam.get("id") or 0),
            exam_name=exam.get("name", ""),
        )


class AppState:
    """Butun oqim uchun yagona holat konteyneri."""

    def __init__(self) -> None:
        self.staff: Optional[Staff] = None
        self.device = DeviceInfo()
        #: Shu mashinaning o'lchangan identifikatori: `mac`, `ip`,
        #: `source`, `adapter` (`system_info.machine_identity`).
        #
        # Handshake uni baribir o'lchaydi va serverga yuboradi
        # (`AuthService.handshake`), shuning uchun natija SHU YERDA
        # saqlanadi: har sahifa o'zi qayta o'lchasa, zaxira yo'lda
        # OS buyrug'i ishga tushib UI ni tutib qolardi va eng
        # yomoni - ekrandagi qiymat serverga yuborilganidan farq
        # qilishi mumkin edi.
        self.machine: dict[str, Any] = {}
        #: Aniqlangan kamera taqsimoti (qaysi kamera nima uchun).
        #
        # Bir marta hisoblanadi (imtihon tanlash sahifasida) va
        # keyingi sahifalar shundan foydalanadi. Har sahifada qaytadan
        # aniqlash ikki sababga ko'ra yaramaydi: qurilmalarni sanash
        # sekin (~0.8 s har bir indeks) va natija farq qilishi mumkin -
        # o'shanda FaceID bitta kamerani, obyekt aniqlash esa
        # boshqasini "birlamchi" deb hisoblardi.
        #
        # Bo'sh `CameraLayout` - "hali aniqlanmagan" va "kamera yo'q"
        # ni bir xil ko'rsatadi. Farq bu yerda kerak emas: ikkalasida
        # ham ishlatiladigan kamera yo'q.
        self.cameras = CameraLayout()
        #: Client aniqlagan unumdorlik profili (`high`/`medium`/`low`/`cpu`).
        #
        # Hozircha BO'SH: apparat aniqlash M6 da qo'shiladi. Maydon
        # ayni paytda kiritildi, chunki uni serverga uzatadigan
        # chaqiruv (`proctoring/start/`) allaqachon mavjud - keyin
        # faqat qiymat to'ldiriladi, shartnoma o'zgarmaydi.
        self.ai_profile: str = ""
        self.exams: list[ExamOption] = []
        self.config: dict[str, Any] = {}
        self.selected_exam: Optional[ExamOption] = None
        self.candidate: Optional[Candidate] = None
        #: Operator kiritgan TO'LIQ JSHSHIR.
        #
        # `Candidate.masked_pinfl` niqoblangan ("3270******0024") va u
        # ekran uchun. Mahalliy arxiv fayl nomida esa to'liq raqam
        # kerak (`services/local_archive.py`): faylni topish va
        # talabgorga bog'lash aynan shu bo'yicha bo'ladi.
        #
        # SERVERGA QAYTA YUBORILMAYDI: u allaqachon qidiruv so'rovida
        # ketgan va sessiyaga muzlatilgan.
        self.pinfl: str = ""
        self.session: Optional[ProctoringSession] = None
        self.exam_access: dict[str, Any] = {}
        #: Sessiya yuz ETALONI - kirishda TASDIQLANGAN jonli kadrning
        #: embedding'i (normallashtirilgan `np.ndarray`).
        #
        # NIMA UCHUN PASPORT EMBEDDING'I EMAS. Test davomidagi savol
        # boshqa: "kirgan odam hali ham shu yerdami?". Bir xil kamera,
        # bir xil yorug'lik va bir xil rakursdagi ikki kadr ancha
        # barqaror ball beradi; pasport rasmi bilan solishtirish esa
        # har safar kirishdagi qiyinchilikni qaytadan boshdan
        # kechirardi. Aynan shu vektor serverda ham `reference_embedding`
        # bo'lib yotadi, ya'ni ball ikkala tomonda bir xil ma'noga ega.
        #
        # SAHIFALAR ORASIDA SHU YERDA UZATILADI: FaceID sahifasi uni
        # yozadi, WebView sahifasi o'qiydi. Ilgari WebView o'zining
        # bo'sh `_last_embedding` ini AI qatlamiga berardi va etalon
        # HAR DOIM `None` bo'lib qolardi - ya'ni client tomondagi
        # `face_mismatch` hodisasi hech qachon tug'ilmasdi.
        self.face_reference: Any = None

    # ------------------------------------------------------------------
    def exam_types(self) -> list[tuple[Optional[int], str]]:
        """Ro'yxatdagi noyob turlar - 2-sahifadagi birinchi select uchun."""
        seen: dict[Optional[int], str] = {}
        for exam in self.exams:
            seen.setdefault(exam.exam_type_id, exam.exam_type_name)
        return sorted(seen.items(), key=lambda item: item[1])

    def exams_of_type(self, exam_type_id) -> list[ExamOption]:
        return [exam for exam in self.exams if exam.exam_type_id == exam_type_id]

    # ------------------------------------------------------------------
    def reset_flow(self) -> None:
        """
        Bitta talabgor oqimini tozalaydi (login holatiga TEGMAYDI).

        Har bir yangi talabgordan oldin chaqiriladi. Tozalanmasa,
        oldingi talabgorning pasport rasmi va challenge'i xotirada
        qolib, keyingisiga aralashib ketishi mumkin.
        """
        self.candidate = None
        self.pinfl = ""
        self.session = None
        self.exam_access = {}
        # Etalon ham tozalanadi: keyingi talabgor oldingisining yuzi
        # bilan solishtirilsa, u imtihon o'rtasida chetlashtirilardi.
        self.face_reference = None

    def reset_all(self) -> None:
        self.reset_flow()
        self.staff = None
        self.device = DeviceInfo()
        # `machine` TOZALANMAYDI: u mashinaning o'zi haqida va
        # xodim chiqib ketgani bilan o'zgarmaydi. Tozalash keyingi
        # login'da uni qaytadan o'lchashga majbur qilardi.
        self.cameras = CameraLayout()
        self.ai_profile = ""
        self.exams = []
        self.config = {}
        self.selected_exam = None
