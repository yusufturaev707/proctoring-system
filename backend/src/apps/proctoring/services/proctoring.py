"""
Proktorlik seansining holat mashinasi.

`ExamSession.status` dan MUSTAQIL. Birinchisi "imtihon qanday
ketyapti" (jarayonda / tugadi / chetlashtirildi), bu esa "kuzatuv
qanday ishlayapti". Ularni birlashtirish "kamera uzildi = imtihon
tugadi" degan noto'g'ri xulosaga olib kelardi — holbuki kamera
uzilishi ko'pincha 15 soniyalik USB nosozligi.

O'TISHLAR ANIQ RO'YXAT bilan cheklangan. Sabab: holat uch joydan
o'zgaradi (client `proctoring/start|stop`, proktor buyrug'i, yakunlash
vazifasi) va ular bir-birini ko'rmaydi. Ro'yxatsiz `completed` dan
`active` ga qaytish kabi o'tishlar jimgina yuz berardi — sessiya
yakunlangandan keyin ham dalil qabul qilinaverardi.

ISHGA TUSHIRISH — YAGONA DARVOZA. `proctoring/start/` imtihon
haqiqatan boshlanadigan nuqta ("START EXAM") va kamera tekshiruvi
aynan shu yerda majburlanadi. Undan oldingi qadamlar (FaceID, shaxs
tasdig'i) ATAYLAB to'silmaydi: ular operatorga nosozlikni ko'rsatish
uchun kerak va ularni bloklash "kamera ishlamayapti" xabarini
ko'rsatadigan ekranga yetib borishga ham imkon bermasdi.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.proctoring.models import ExamSession, ProctoringState

logger = logging.getLogger(__name__)

#: Ruxsat etilgan o'tishlar. Bo'sh to'plam — terminal holat.
_TRANSITIONS: dict[str, set] = {
    ProctoringState.IDLE: {
        ProctoringState.CAMERA_CHECK,
        ProctoringState.STARTING,
        ProctoringState.FAILED,
    },
    ProctoringState.CAMERA_CHECK: {
        ProctoringState.CAMERA_CHECK,
        ProctoringState.READY,
        ProctoringState.FAILED,
    },
    ProctoringState.READY: {
        ProctoringState.CAMERA_CHECK,
        ProctoringState.STARTING,
        ProctoringState.FAILED,
    },
    ProctoringState.STARTING: {ProctoringState.ACTIVE, ProctoringState.FAILED},
    ProctoringState.ACTIVE: {
        ProctoringState.DEGRADED,
        ProctoringState.PAUSED,
        ProctoringState.FINISHING,
        ProctoringState.COMPLETED,
    },
    ProctoringState.DEGRADED: {
        ProctoringState.ACTIVE,
        ProctoringState.PAUSED,
        ProctoringState.FINISHING,
        ProctoringState.COMPLETED,
    },
    ProctoringState.PAUSED: {
        ProctoringState.ACTIVE,
        ProctoringState.DEGRADED,
        ProctoringState.FINISHING,
        ProctoringState.COMPLETED,
    },
    ProctoringState.FINISHING: {ProctoringState.COMPLETED},
    ProctoringState.COMPLETED: set(),
    # Muvaffaqiyatsizlikdan QAYTISH mumkin: operator kamerani ulab,
    # tekshiruvni takrorlaydi. Aks holda bitta uzilgan kabel butun
    # ish o'rnini kun oxirigacha yaroqsiz qilardi.
    ProctoringState.FAILED: {ProctoringState.CAMERA_CHECK, ProctoringState.IDLE},
}


class CameraCheckRequired(DomainError):
    """Kamera tekshiruvi o'tkazilmagan yoki eskirgan."""

    default_code = "camera_check_required"
    default_detail = "Kamera tekshiruvi o'tkazilmagan yoki eskirgan"


class CameraCheckFailed(DomainError):
    """Tekshiruv natijasi siyosat talablariga mos kelmadi."""

    default_code = "camera_check_failed"
    default_detail = "Kamera tekshiruvi siyosat talablariga mos kelmadi"


class InvalidProctoringState(DomainError):
    default_code = "invalid_proctoring_state"
    default_detail = "Kuzatuv holatini o'zgartirib bo'lmaydi"


# --------------------------------------------------------------------------
def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, set())


def transition(session: ExamSession, target: str, *, reason: str = "") -> ExamSession:
    """
    Holatni o'zgartiradi. Ruxsat etilmagan o'tish — istisno.

    Bir xil holatga o'tish JIMGINA o'tkazib yuboriladi (xato emas):
    client qayta ulanishda `start` ni takrorlashi mumkin va bu
    normal holat.
    """
    current = session.proctoring_state
    if current == target:
        return session

    if not can_transition(current, target):
        raise InvalidProctoringState(
            "Kuzatuv holati '{}' dan '{}' ga o'ta olmaydi".format(current, target)
        )

    session.proctoring_state = target
    session.save(update_fields=["proctoring_state", "updated_at"])
    logger.info(
        "Kuzatuv holati: %s %s -> %s%s",
        session.public_id, current, target, " ({})".format(reason) if reason else "",
    )
    return session


# --------------------------------------------------------------------------
def start(session: ExamSession, *, snapshot: dict | None, policy: dict) -> dict:
    """
    Kuzatuvni ishga tushiradi — imtihon boshlanishidan OLDINGI darvoza.

    Tekshiruv suratchasi ikki sababdan rad etilishi mumkin va ular
    operator uchun BOSHQA-BOSHQA:

      * umuman yo'q yoki eskirgan -> tekshiruvni takrorlash kerak;
      * bor, lekin talablarga mos emas -> uskunani tuzatish kerak.

    Ikkalasini bitta xatoga qo'shib yuborish operatorni "nima
    qilay?" degan savol bilan qoldirardi.
    """
    camera_policy = (policy or {}).get("camera") or {}
    require_check = bool(settings.PROCTORING["REQUIRE_CAMERA_CHECK"])
    needs_camera = bool(
        camera_policy.get("primary_required", True)
        or camera_policy.get("secondary_required", False)
    )

    if snapshot is None:
        # Tekshiruv YO'Q. Siyosat kamerani talab qilmasa, bu to'siq
        # emas: kuzatuvsiz imtihon ham qonuniy konfiguratsiya
        # (masalan mashq testi).
        if require_check and needs_camera:
            raise CameraCheckRequired()
        logger.info(
            "Kuzatuv tekshiruvsiz boshlandi: %s (siyosat kamerani talab qilmaydi)",
            session.public_id,
        )
    elif not snapshot.get("can_start"):
        raise CameraCheckFailed(
            "Kamera tekshiruvidan o'tmadi: {}".format(
                ", ".join(snapshot.get("blockers") or []) or "sabab noma'lum"
            )
        )

    transition(session, ProctoringState.STARTING, reason="client start")

    updates = ["proctoring_state", "updated_at"]
    if snapshot is not None:
        # Suratcha SESSIYAGA KO'CHIRILADI. Redis'dagisi vaqtinchalik
        # (TTL bilan o'chadi), bu esa dalil: "nega bu mashinada
        # ikkinchi kamerasiz boshlandi?" degan savolga javob faqat
        # shu yozuvdan topiladi.
        session.camera_check = snapshot
        updates.append("camera_check")

    session.proctoring_state = ProctoringState.ACTIVE
    session.save(update_fields=updates)
    logger.info("Kuzatuv faollashdi: %s", session.public_id)

    return {
        "state": session.proctoring_state,
        "policy": policy or {},
        "camera_check": {
            "status": (snapshot or {}).get("status", "unknown"),
            "checked": snapshot is not None,
        },
        "started_at": timezone.now(),
    }


def stop(session: ExamSession, *, reason: str = "") -> ExamSession:
    """
    Kuzatuvni yakunlaydi.

    Har qanday holatdan chaqirilishi mumkin va u XATO BERMAYDI:
    yakunlash yo'lida turgan to'siq imtihonni yopilmagan holda
    qoldirardi. Boshlanmagan kuzatuv jimgina `completed` ga o'tadi.
    """
    if session.proctoring_state == ProctoringState.COMPLETED:
        return session

    if session.proctoring_state in (ProctoringState.IDLE, ProctoringState.CAMERA_CHECK,
                                    ProctoringState.READY, ProctoringState.FAILED):
        # Kuzatuv umuman boshlanmagan — o'tish jadvali bu yo'lni
        # ochmaydi, lekin natija bir xil bo'lishi kerak.
        session.proctoring_state = ProctoringState.COMPLETED
        session.save(update_fields=["proctoring_state", "updated_at"])
        return session

    if session.proctoring_state != ProctoringState.FINISHING:
        transition(session, ProctoringState.FINISHING, reason=reason or "stop")
    return transition(session, ProctoringState.COMPLETED, reason=reason or "stop")


def degrade(session: ExamSession, *, reason: str) -> ExamSession:
    """
    Cheklangan rejim: kuzatuv ISHLAYAPTI, lekin to'liq emas.

    Imtihonni TO'XTATMAYDI. Qaror siyosatda
    (`ProctoringPolicy.camera_lost_action`) va uni proktor yoki
    yakunlash vazifasi qabul qiladi.
    """
    if session.proctoring_state != ProctoringState.ACTIVE:
        return session
    return transition(session, ProctoringState.DEGRADED, reason=reason)


def restore(session: ExamSession, *, reason: str = "") -> ExamSession:
    if session.proctoring_state != ProctoringState.DEGRADED:
        return session
    return transition(session, ProctoringState.ACTIVE, reason=reason or "restored")
