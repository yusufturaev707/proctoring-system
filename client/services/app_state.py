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
    inventory_code: str = ""
    zone_id: Optional[int] = None
    zone_name: str = ""
    cameras: list = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return self.status == "active"

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
    photo_base64: str = ""
    photo_url: str = ""
    has_reference_face: bool = False
    platform_status: str = ""
    schedule: Optional[dict] = None

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
            photo_base64=data.get("photo_base64", "") or "",
            photo_url=data.get("photo_url", "") or "",
            has_reference_face=bool(payload.get("has_reference_face")),
            platform_status=platform.get("status", ""),
            schedule=payload.get("schedule"),
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
        self.exams: list[ExamOption] = []
        self.config: dict[str, Any] = {}
        self.selected_exam: Optional[ExamOption] = None
        self.candidate: Optional[Candidate] = None
        self.session: Optional[ProctoringSession] = None
        self.exam_access: dict[str, Any] = {}

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
        self.session = None
        self.exam_access = {}

    def reset_all(self) -> None:
        self.reset_flow()
        self.staff = None
        self.device = DeviceInfo()
        self.exams = []
        self.config = {}
        self.selected_exam = None
