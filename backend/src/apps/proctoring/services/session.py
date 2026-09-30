"""
Imtihon sessiyasining hayot sikli.

Oqim:
    1. lookup_candidate()   JSHSHIR -> tashqi API -> Candidate (+challenge)
    2. verify_initial_face() FaceID -> ExamSession yaratiladi
    3. issue_exam_access()   bir martalik tashqi token + WebView konfiguratsiyasi
    4. ... monitoring ...
    5. finish_session() / terminate_session()

YUZ SOLISHTIRISHI BU YERDA EMAS. Ikkala embedding ham clientda
bo'ladi (etalon - pasport rasmidan yoki kirishdagi kadrdan, jonli
vektor - hozirgi kadrdan) va cosine o'sha yerda hisoblanadi. Serverga
BALL keladi, chegara esa imtihonga biriktirilgan sozlamadan olinadi
(`Setting.faceid_min_score_student` / `faceid_min_score_exam`).

Server nima qiladi: chegarani qo'llaydi, natijani `FaceVerificationLog`
ga yozadi, jonli kadrni saqlaydi, hisoblagichni yuritadi va
chetlashtirish qarorini chiqaradi. Ya'ni "ball qanday chiqdi" client
tomonda, "ball nima bilan tugaydi" server tomonda.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import (
    CandidateNotEligible,
    ExamNotOpen,
    ExternalPlatformError,
    FaceVerificationFailed,
    IdentityAlreadyConfirmed,
    IdentityNotConfirmed,
    SessionAlreadyActive,
    SessionNotFound,
)
from apps.common.utils.crypto import (
    encrypt,
    generate_token,
    hash_token,
    mask_pinfl,
    normalize_pinfl,
)
from apps.proctoring.models import (
    ExamSession,
    FaceVerificationLog,
    ProctoringEvent,
)
from apps.proctoring.services import state as session_state

logger = logging.getLogger(__name__)

#: Tashqi platformada test yakunlangan hisoblanadigan statuslar —
#: bunday sessiyaga WebView ochilmaydi.
_CLOSED_PLATFORM_STATUSES = frozenset(
    {"finished", "completed", "submitted", "closed", "expired", "cancelled"}
)


def _parse_dt(value):
    """Tashqi platformadan kelgan ISO vaqtni `datetime` ga aylantiradi."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        logger.warning("Tashqi platforma vaqtini o'qib bo'lmadi: %r", value)
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


# --------------------------------------------------------------------------
# 1-qadam: JSHSHIR bo'yicha talabgorni aniqlash
# --------------------------------------------------------------------------
def lookup_candidate(
    *, pinfl: str, exam, device=None, zone=None, ip_address: str = "",
    machine_uuid: str = "", mac_address: str = "",
) -> dict:
    """
    Tashqi platformadan talabgorni oladi va `Candidate` yozuvini yangilaydi.

    Bu yerda hali sessiya YARATILMAYDI — faqat `challenge` beriladi.
    Sabab: FaceID'dan o'tmagan talabgor uchun DB'da sessiya qatorlari
    yaratish keraksiz yozish va noto'g'ri statistika demak.

    Eng birinchi tekshiruv — kirish oynasi. Tashqi API'ga oyna yopiq
    bo'lsa umuman tegilmaydi.

    SO'ROVNI SERVER YUBORADI. Client platformaga hech qachon o'zi
    murojaat qilmaydi (`integrations/exam_site.py` docstring'i):
    manzil (`Exam.site_url`) va kredensial
    (`Exam.site_header_encrypted`) shu yerda qoladi, client esa
    faqat tayyor natijani oladi.
    """
    from apps.exams import services as exam_services
    from apps.integrations import exam_site

    from apps.exams import bookings

    schedule = _require_open_schedule(exam, zone)

    pinfl = normalize_pinfl(pinfl)

    # KOMPYUTER BRONI — TASHQI PLATFORMADAN OLDIN. Tekshiruv mahalliy va
    # arzon; talabgor noto'g'ri stolda bo'lsa platformaga so'rov
    # yuborishning ma'nosi yo'q (u yerda ham limit bor). Xato javobida
    # qaysi kompyuterga borish kerakligi TUZILGAN holda keladi
    # (`WrongComputer.extra`), client uni matndan ajratmaydi.
    #
    seat = bookings.resolve_candidate_seat(
        schedule=schedule, pinfl=pinfl, device=device,
        machine_uuid=machine_uuid, mac_address=mac_address,
    )
    # `CandidateNotFound` / `CandidateNotEligible` shu yerdan ko'tariladi
    # va ular client uchun BOSHQA-BOSHQA holat (`exam_site._normalize`).
    data = exam_site.check_candidate(
        site_url=exam.site_url,
        site_header=exam_services.get_site_header(exam),
        pinfl=pinfl,
    )

    # Faol sessiya allaqachon bormi (boshqa kompyuterda)?
    existing = (
        ExamSession.objects.filter(
            pinfl=pinfl,
            exam=exam,
            exam_date=timezone.localdate(),
        )
        .exclude(status__in=ExamSession.TERMINAL_STATUSES)
        .first()
    )
    if existing is not None and existing.computer_id and device is not None:
        if existing.device_id and existing.device_id != device.pk:
            raise SessionAlreadyActive()

    # Talabgor ma'lumoti challenge bilan birga tashiladi — sessiya
    # FaceID'dan keyin yaratiladi va shu ma'lumot unga MUZLATIB yoziladi.
    challenge = generate_token(24)
    session_state.store_pending(
        challenge,
        {
            "pinfl": pinfl,
            "last_name": data.get("last_name", ""),
            "first_name": data.get("first_name", ""),
            "middle_name": data.get("middle_name", ""),
            "external_candidate_id": data.get("external_id", ""),
            "external_abitur_id": data.get("abitur_id", ""),
            # Platforma bergan test havolasi — WebView AYNAN shuni
            # ochadi. Havola SHU YERDA olinadi va sessiyaga
            # muzlatiladi: uni WebView ochilayotganda qayta so'rash
            # platformada yangi havola yaratib, eskisini bekor
            # qilishi mumkin.
            "external_test_link": data.get("test_link", ""),
            # Platforma ruxsat bergani uchun status "allowed".
            #
            # `is_finished` BU YERGA TUSHMAYDI va bu ataylab: uni
            # `finished` deb yozish `_CLOSED_PLATFORM_STATUSES` orqali
            # WebView'ni to'sardi — holbuki platformaning O'Z
            # namunasida `is_finished: 1` bo'lgani holda `status: true`
            # va "Testga ruxsat!" qaytadi. Ya'ni bu maydon "test
            # tugagan" degani EMAS va uni to'siq sifatida talqin
            # qilish talabgorni imtihonga qo'ymasdi. Qiymatning o'zi
            # `meta` da dalil sifatida saqlanadi.
            "external_status": "allowed",
            "platform_is_finished": bool(data.get("is_finished")),
            "platform_message": data.get("message", ""),
            # Test davomiyligi (daqiqa). U sessiyaga MUZLATILADI:
            # platforma qiymatni keyin o'zgartirsa ham, bayonnomada
            # talabgorga AYNAN qancha vaqt berilgani qolishi kerak.
            "duration_minutes": int(data.get("duration_minutes") or 0),
            "exam_id": exam.pk,
            # Qaysi seansga tegishli ekani AYNAN SHU YERDA aniqlangan,
            # aks holda `ExamSession.schedule` NULL qolardi.
            "schedule_id": getattr(schedule, "pk", None),
            "device_id": getattr(device, "pk", None),
            "ip": ip_address,
            # Bron bo'yicha joy — sessiyaga MUZLATILADI: keyin talabgor
            # boshqa joyga ko'chirilsa ham bayonnomada qayerda
            # o'tirgani qoladi.
            "seat": seat,
        },
    )

    # Platforma to'liq ismni bitta maydonda bergan bo'lsa (`fio`), u
    # ustun: bo'laklardan yig'ish tartibni buzishi mumkin (ba'zi
    # platformalarda "Ism Familiya", ba'zilarida teskari).
    full_name = data.get("full_name", "") or " ".join(
        part
        for part in (
            data.get("last_name", ""), data.get("first_name", ""), data.get("middle_name", "")
        )
        if part
    ).strip()

    # Etalon rasm — client kirishdagi FaceID'da AYNAN shuni kameradagi
    # yuz bilan solishtiradi. Rasm DB'ga yozilmaydi va sessiyaga
    # muzlatilmaydi: u faqat shu tekshiruv uchun, bir marta uzatiladi.
    reference_photo = data.get("photo_base64", "") or ""

    return {
        "challenge": challenge,
        "candidate": {
            "full_name": full_name,
            "last_name": data.get("last_name", ""),
            "first_name": data.get("first_name", ""),
            "middle_name": data.get("middle_name", ""),
            "masked_pinfl": mask_pinfl(pinfl),
            "external_candidate_id": data.get("external_id", ""),
            "abitur_id": data.get("abitur_id", ""),
            "photo_key": "",
            # `photo_url` — rasm tashqi manzilda bo'lsa; `photo_base64` —
            # bevosita kelgan bo'lsa. Client qaysi biri bo'lsa shuni oladi.
            "photo_url": data.get("photo_url", ""),
            "photo_base64": reference_photo,
        },
        # Etalon rasm kelgan bo'lsa — solishtirish mumkin. Kelmasa client
        # "enrollment" rejimida ishlaydi: yuz qayd etiladi, lekin hujjat
        # bo'yicha tasdiq butunlay operator zimmasida qoladi.
        "has_reference_face": bool(reference_photo or data.get("photo_url")),
        "challenge_expires_in": settings.PROCTORING["PENDING_SESSION_TTL"],
        # Bron bo'yicha joy (`None` — bu sessiyada bron yuritilmaydi).
        # Client uni natija kartasida "joy tasdiqlandi" deb ko'rsatadi.
        "seat": seat,
        # Platformaning O'Z javobi. `message` — AYNAN u aytgan matn
        # ("Testga ruxsat!") va client uni o'zgartirmasdan ko'rsatadi:
        # sabab platformada, biz esa uni faqat yetkazamiz.
        #
        # `test_link` bu yerda YO'Q va bo'lmasligi kerak: u WebView
        # ochilayotganda, shaxs tasdiqlangandan keyin beriladi
        # (`exam/access/`). Uni JSHSHIR tekshiruvida berish
        # FaceID'ni butunlay chetlab o'tish imkonini berardi.
        "platform": {
            "message": data.get("message", ""),
            "is_finished": bool(data.get("is_finished")),
            "status": "finished" if data.get("is_finished") else "allowed",
        },
        # Test davomiyligi DAQIQADA va shu birlikda ketadi: "3 soat"
        # ko'rinishi TAQDIMOT qarori va u client tomonda qabul
        # qilinadi (`Candidate.duration_label`). Serverda formatlash
        # matnni tarjima qilib bo'lmaydigan holga keltirardi.
        #
        # 0 — "platforma aytmadi": client bunda maydonni umuman
        # ko'rsatmaydi ("0 daqiqa" yozuvi yolg'on bo'lardi).
        "duration_minutes": int(data.get("duration_minutes") or 0),
        # Client imtihon tugash vaqtini bilishi kerak (sanoq va avtomatik yopish).
        "schedule": (
            {
                "id": schedule.pk,
                "starts_at": schedule.starts_at,
                "ends_at": schedule.ends_at,
            }
            if schedule is not None
            else None
        ),
    }


def _require_open_schedule(exam, zone):
    """
    Kirish oynasi tekshiruvi (`ExamSchedule`).

    `ExamSchedule` aynan shu uchun kiritilgan: oynadan tashqarida JSHSHIR
    qidiruvi ochiq qolsa, u fuqarolarning F.I.Sh. sini 24/7 qidirish
    servisiga aylanadi.

    Jadval umuman tuzilmagan bo'lsa tekshiruv o'chirilgan hisoblanadi —
    `is_ip_allowed` dagi bilan bir xil qoida. `REQUIRE_EXAM_SCHEDULE=true`
    bu yumshoqlikni o'chiradi (production uchun tavsiya).
    """
    from apps.exams import selectors as exam_selectors

    zone_id = getattr(zone, "pk", None)
    schedule, error = exam_selectors.resolve_open_schedule(exam_id=exam.pk, zone_id=zone_id)

    if schedule is not None:
        return schedule

    if error == "no_schedule" and not settings.PROCTORING["REQUIRE_EXAM_SCHEDULE"]:
        logger.warning(
            "Imtihon %s uchun jadval tuzilmagan — kirish oynasi tekshirilmadi", exam.pk
        )
        return None

    upcoming = exam_selectors.next_schedule(exam_id=exam.pk, zone_id=zone_id)
    if upcoming is not None:
        raise ExamNotOpen(
            f"Kirish oynasi {timezone.localtime(upcoming.opens_at):%d.%m.%Y %H:%M} da ochiladi"
        )
    raise ExamNotOpen("Bu imtihon uchun rejalashtirilgan seans topilmadi")


def _require_pending_device(pending: dict | None, device) -> dict:
    """
    Challenge'ni FAQAT uni olgan qurilma ishlata oladi.

    JSHSHIR tekshiruvidagi hamma qaror (kompyuter broni, "boshqa
    kompyuterda faol sessiya bor") SHU qurilma uchun chiqarilgan.
    Ilgari `device_id` pending'ga yozilar, lekin hech qayerda
    solishtirilmasdi: bron tekshiruvi faqat "JSHSHIR to'g'ri
    mashinada kiritildi" ni isbotlardi, sessiya esa challenge'ni
    bilgan istalgan mashinada ochilishi mumkin edi.

    Rad javobi "muddati tugagan" bilan BIR XIL (`SessionNotFound`):
    "challenge bor, lekin boshqa qurilmaniki" degan alohida javob
    tirik challenge'larni sanab chiqishga yo'l ochardi.

    Pending'da qurilma yo'q bo'lsa (`REQUIRE_DEVICE_ID=false`, dev)
    tekshiruv o'tkazib yuboriladi — solishtiradigan narsa yo'q.
    """
    if pending is None:
        raise SessionNotFound("Tekshiruv muddati tugagan, qaytadan urinib ko'ring")

    expected = pending.get("device_id")
    actual = getattr(device, "pk", None)
    if expected is not None and actual != expected:
        logger.warning(
            "Challenge begona qurilmadan ishlatildi: kutilgan=%s kelgan=%s jshshir=%s",
            expected, actual, mask_pinfl(pending.get("pinfl", "")),
        )
        raise SessionNotFound("Tekshiruv muddati tugagan, qaytadan urinib ko'ring")
    return pending


# --------------------------------------------------------------------------
# 2-qadam: kirishdagi yuz tekshiruvi -> sessiya yaratish
# --------------------------------------------------------------------------
@transaction.atomic
def verify_initial_face(
    *,
    challenge: str,
    embedding: list[float] | None,
    score: int | None,
    image: bytes | None = None,
    reference_image: bytes | None = None,
    image_key: str = "",
    faces_detected: int = 1,
    device=None,
    computer=None,
    ip_address: str = "",
) -> ExamSession:
    """
    Sessiyani yaratadi va yuz etalonini qayd etadi.

    SOLISHTIRISH CLIENTDA bo'lib bo'lgan: pasport rasmidan olingan
    etalon ham, jonli kadr ham o'sha yerda edi. Bu yerga uning
    NATIJASI keladi — ball va o'sha paytdagi kadr.

    Ball CHEGARA bilan solishtiriladi (`faceid_min_score_student`,
    imtihonga biriktirilgan sozlamadan). Bu SHARTNOMA tekshiruvi,
    xavfsizlik chegarasi emas: ballni client hisoblaydi va uni
    o'zgartirish mumkin. Haqiqiy chegara avvalgidek operatorning
    hujjat bo'yicha tasdig'i:

        FaceID kafolati    : "sessiya davomida odam almashtirilmadi"
        Shaxs kafolati     : operatorning hujjat bo'yicha tekshiruvi

    Etalon rasm bo'lmasa (platforma bermagan) client ball YUBORMAYDI —
    enrollment rejimi. O'shanda chegara ham qo'llanmaydi:
    solishtiriladigan narsaning o'zi yo'q.

    Jonli kadr DALIL sifatida saqlanadi va u TO'SIQ EMAS: rasmni
    saqlab bo'lmasa sessiya baribir ochiladi (sabab log'da qoladi),
    aks holda buzilgan JPEG imtihonni to'xtatardi.
    """
    from apps.common.utils.vectors import normalize
    from apps.controls import services as controls_services
    from apps.proctoring.services import face_images

    # Avval O'QILADI va qurilma tekshiriladi, keyin sarflanadi: begona
    # qurilmadan kelgan so'rov haqiqiy egasining challenge'ini yo'q
    # qilib qo'ymasligi kerak. Sarflash baribir atomik (GET+DEL bitta
    # MULTI'da) — ikki parallel so'rovdan faqat bittasi sessiya ochadi.
    _require_pending_device(session_state.peek_pending(challenge), device)
    pending = session_state.consume_pending(challenge)
    if pending is None:
        raise SessionNotFound("Tekshiruv muddati tugagan, qaytadan urinib ko'ring")

    from apps.exams.models import Exam

    exam = Exam.objects.select_related("setting").get(pk=pending["exam_id"])
    # Sozlama AYNAN SHU YERDA olinadi — imtihon endigina ma'lum bo'ldi.
    config = controls_services.get_client_config(exam)
    face_required = bool(config["face"]["enabled_student"])
    threshold = int(config["face"]["min_score_initial"])

    # Etalonni olish uchun aynan bitta yuz ko'rinishi shart.
    if face_required and (not embedding or faces_detected != 1):
        _log_face_attempt(
            pinfl=pending.get("pinfl", ""),
            faces_detected=faces_detected,
            reason="no_embedding" if not embedding else "faces_detected",
        )
        raise FaceVerificationFailed(
            "Kamerada aynan bitta yuz aniq ko'rinishi kerak "
            f"(topilgani: {faces_detected})"
        )

    # Chegaradan past ball bilan kelgan client SHARTNOMANI buzgan:
    # bunday urinish `face/attempt/` ga borishi kerak edi. Sessiya
    # ochilmaydi — aks holda "mos kelmadi" yozuvi bilan ochilgan
    # sessiya paydo bo'lardi va uni bayonnomada tushuntirib bo'lmasdi.
    if face_required and score is not None and int(score) < threshold:
        _log_face_attempt(
            pinfl=pending.get("pinfl", ""),
            faces_detected=faces_detected,
            reason=f"score:{int(score)}<{threshold}",
        )
        raise FaceVerificationFailed(
            f"Yuz mos kelmadi: o'xshashlik {int(score)}%, talab {threshold}%"
        )

    session = _create_session(
        pending=pending,
        exam=exam,
        device=device,
        computer=computer,
        ip_address=ip_address,
        reference_embedding=normalize(embedding) if embedding else None,
    )

    # AVVAL FAYL, KEYIN QATOR. Qator yozilmasa fayl darhol o'chiriladi —
    # aks holda hech kim bilmaydigan yetim fayl qolardi.
    image_path, image_purge_after = _store_face_image(
        image, exam_id=exam.pk, session=session, config=config
    )
    # ETALON HAM SAQLANADI va faqat SHU YERDA (kirish tekshiruvi).
    # Ballning o'zi hech narsani isbotlamaydi: apellyatsiyada
    # hujjatdagi odam va kameradagi odam YONMA-YON kerak bo'ladi.
    reference_path, reference_purge = _store_face_image(
        reference_image,
        exam_id=exam.pk,
        session=session,
        config=config,
        kind="reference",
    )
    try:
        FaceVerificationLog.objects.create(
            session=session,
            exam=exam,
            zone=session.zone,
            pinfl=session.pinfl or "",
            stage=FaceVerificationLog.Stage.INITIAL,
            source=FaceVerificationLog.Source.CLIENT,
            # Ball endi YOZILADI (ilgari 0 edi): u clientdagi
            # solishtiruvning yagona izi va apellyatsiyada "qanday
            # o'xshashlik bilan kiritilgan?" degan savolga javob beradi.
            score=_clamp_score(score),
            threshold=threshold,
            passed=bool(embedding),
            faces_detected=faces_detected,
            image_key=image_key,
            image_path=image_path,
            reference_image_path=reference_path,
            # Ikkala fayl BIR VAQTDA tozalanadi: ular bitta
            # tekshiruvning ikki tomoni va bittasini qoldirish
            # yarim dalil berardi.
            image_purge_after=image_purge_after or reference_purge,
            occurred_at=timezone.now(),
        )
    except Exception:
        face_images.discard(image_path)
        face_images.discard(reference_path)
        raise

    # Shaxs hali tasdiqlanmagan — operator hujjat bilan tasdiqlamaguncha
    # `issue_exam_access` imtihonni ochmaydi. Hodisa YARATILMAYDI: bu holat
    # har bir sessiyada uchraydi, ya'ni hodisa oqimida sof shovqin bo'lardi.
    session.meta = {**(session.meta or {}), "identity": {"verified": False}}
    session.save(update_fields=["meta", "updated_at"])

    return session


def record_entry_face_failure(
    *,
    challenge: str,
    score: int | None,
    faces_detected: int = 1,
    image: bytes | None = None,
    reference_image: bytes | None = None,
    device=None,
    computer=None,
) -> dict:
    """
    Kirishda MOS KELMAGAN urinish: rasm va ball, SESSIYASIZ.

    NIMA UCHUN ALOHIDA YO'L. Sessiya faqat moslik tasdiqlangach
    ochiladi, ya'ni "kira olmadi" holatini sessiyaga bog'lab
    bo'lmaydi. Aynan o'sha holat esa eng qimmatli yozuv: kadrda
    boshqa odam turgan bo'lishi mumkin va u izsiz yo'qolmasligi
    kerak.

    CHALLENGE SARFLANMAYDI (`peek_pending`): qayta urinish kutilgan
    xulq (yorug'lik, ko'zoynak, bosh burilishi). Sarflansa, har bir
    muvaffaqiyatsiz kadrdan keyin talabgor qaytadan JSHSHIR
    kiritishga majbur bo'lardi.

    Qaytadi: `{"recorded", "score", "threshold", "attempts"}`.
    `attempts` operatorga ko'rsatiladi ("3-urinish"): ketma-ket
    muvaffaqiyatsizlik hujjatni qo'lda tekshirishni boshlash
    signalidir.
    """
    from apps.controls import services as controls_services
    from apps.proctoring.services import face_images

    pending = session_state.peek_pending(challenge)
    _require_pending_device(pending, device)

    from apps.exams.models import Exam

    exam = Exam.objects.select_related("setting").get(pk=pending["exam_id"])
    config = controls_services.get_client_config(exam)
    threshold = int(config["face"]["min_score_initial"])
    pinfl = pending.get("pinfl", "")
    zone = computer.zone if computer is not None else None
    occurred_at = timezone.now()

    image_path, image_purge_after = _store_face_image(
        image, exam_id=exam.pk, session=None, config=config
    )
    reference_path, reference_purge = _store_face_image(
        reference_image, exam_id=exam.pk, session=None, config=config, kind="reference"
    )
    try:
        log_row = FaceVerificationLog.objects.create(
            session=None,
            exam=exam,
            zone=zone,
            pinfl=pinfl,
            stage=FaceVerificationLog.Stage.INITIAL,
            source=FaceVerificationLog.Source.CLIENT,
            score=_clamp_score(score),
            threshold=threshold,
            passed=False,
            faces_detected=faces_detected,
            image_path=image_path,
            reference_image_path=reference_path,
            image_purge_after=image_purge_after or reference_purge,
            occurred_at=occurred_at,
        )
    except Exception:
        face_images.discard(image_path)
        face_images.discard(reference_path)
        raise

    # Urinishlar SUTKA emas, 12 soat oynasida sanaladi: bir kunda
    # ikkita seans bo'lishi mumkin va ertalabki urinishlar kechki
    # imtihonda "10-urinish" bo'lib ko'rinishi operatorni chalg'itardi.
    attempts = FaceVerificationLog.objects.filter(
        pinfl=pinfl,
        exam=exam,
        stage=FaceVerificationLog.Stage.INITIAL,
        passed=False,
        occurred_at__gte=occurred_at - timedelta(hours=12),
    ).count()

    # Qurilma log'da: "qaysi mashinada kira olmayapti?" degan savol
    # operatorda birinchi bo'lib tug'iladi va unga javob beradigan
    # boshqa yozuv yo'q (sessiya yaratilmagan).
    logger.info(
        "Kirishdagi FaceID mos kelmadi: pinfl=%s ball=%s/%s yuzlar=%s "
        "urinish=%s qurilma=%s",
        mask_pinfl(pinfl), _clamp_score(score), threshold, faces_detected,
        attempts, getattr(device, "device_id", "-"),
    )
    return {
        "recorded": True,
        "id": log_row.pk,
        "score": _clamp_score(score),
        "threshold": threshold,
        "attempts": attempts,
    }


def _clamp_score(score) -> int:
    """
    Ball 0..100 oralig'ida.

    Client uni O'ZI hisoblaydi, ya'ni qiymat ixtiyoriy bo'lishi
    mumkin. Serializer ham tekshiradi, lekin service to'g'ridan-to'g'ri
    (testlardan, kelajakdagi boshqa yuzadan) chaqirilishi mumkin —
    va o'shanda `PositiveSmallIntegerField` ga manfiy qiymat yozish
    DB darajasida yiqilardi.
    """
    try:
        return max(0, min(100, int(score or 0)))
    except (TypeError, ValueError):
        return 0


def _store_face_image(image, *, exam_id, session, config: dict, kind: str = "live") -> tuple:
    """
    Kadrni saqlaydi. Xato TASHLAMAYDI.

    `kind="reference"` - hujjat (pasport) rasmi, `kind="live"` -
    kameradan olingan kadr.

    Rasm dalil, to'siq emas: uni saqlab bo'lmagani uchun tekshiruvni
    rad etish buzilgan JPEG tufayli butun imtihonni to'xtatardi.
    """
    if not image:
        return "", None

    from apps.proctoring.services import face_images

    try:
        return face_images.store(
            data=image,
            exam_id=exam_id,
            session=session,
            policy=config.get("proctoring") or {},
            kind=kind,
        )
    except Exception:
        logger.warning("FaceID rasmi saqlanmadi", exc_info=True)
        return "", None


# --------------------------------------------------------------------------
# Operator tasdig'i — shaxsni aniqlashning YAGONA ishonchli nuqtasi
# --------------------------------------------------------------------------
@transaction.atomic
def confirm_identity(
    session: ExamSession,
    *,
    actor,
    document_type: str,
    document_number: str,
    note: str = "",
) -> ExamSession:
    """
    Operator talabgor shaxsini hujjat bo'yicha tasdiqlaydi.

    Tasdiq BIR MARTA beriladi: qayta yozish audit izini buzadi va
    "kim tasdiqlagan" savoliga ikki xil javob paydo bo'ladi.
    """
    if session.identity_verified:
        raise IdentityAlreadyConfirmed()
    if session.status in ExamSession.TERMINAL_STATUSES:
        raise SessionNotFound("Sessiya yakunlangan")

    session.meta = {
        **(session.meta or {}),
        "identity": {
            "verified": True,
            "by_id": actor.pk,
            "by": actor.username,
            "by_full_name": actor.get_full_name(),
            "at": timezone.now().isoformat(),
            "document_type": document_type,
            "document_number": document_number,
            "note": note[:500],
        },
    }
    session.save(update_fields=["meta", "updated_at"])

    logger.info(
        "Shaxs tasdiqlandi: session=%s operator=%s hujjat=%s",
        session.public_id, actor.username, document_type,
    )
    return session


def reject_identity(session: ExamSession, *, actor, reason: str) -> ExamSession:
    """
    Hujjat mos kelmadi — sessiya darhol tugatiladi.

    Bu "tasdiqlamay qo'yaqolish" dan farq qiladi: tasdiqlanmagan sessiya
    shunchaki ochilmaydi, rad etilgani esa CHETLASHTIRILADI va dalil
    sifatida qayd etiladi.
    """
    session.meta = {
        **(session.meta or {}),
        "identity": {
            "verified": False,
            "rejected": True,
            "by_id": actor.pk,
            "by": actor.username,
            "at": timezone.now().isoformat(),
            "reason": reason[:500],
        },
    }
    session.save(update_fields=["meta", "updated_at"])

    logger.warning(
        "Shaxs RAD ETILDI: session=%s operator=%s sabab=%s",
        session.public_id, actor.username, reason,
    )
    return terminate_session(
        session, actor=actor, reason=f"Shaxs tasdiqlanmadi: {reason}"
    )


def _create_session(
    *, pending: dict, exam, device, computer, ip_address, reference_embedding=None
) -> ExamSession:
    exam_date = timezone.localdate()
    pinfl = pending["pinfl"]

    # "Bitta talabgor = bitta faol sessiya" — atomik Redis qulfi.
    owner = f"dev:{getattr(device, 'pk', 'na')}"
    if not session_state.lock_candidate(pinfl, exam.pk, owner):
        raise SessionAlreadyActive()

    # Urinish raqami KUN ichida hisoblanadi — boshqa sanadagi imtihon
    # yangi sessiya sifatida 1-urinishdan boshlanadi.
    last_attempt = (
        ExamSession.objects.filter(pinfl=pinfl, exam=exam, exam_date=exam_date)
        .order_by("-attempt_no")
        .values_list("attempt_no", flat=True)
        .first()
    )

    zone = computer.zone if computer is not None else None
    # MANZIL CLIENTDAN. `ip_address` - server ko'rgan manba manzili va
    # u panelda foydasiz bo'lib chiqdi: bino ichidagi serverda u
    # LAN manzil, dev'da esa `127.0.0.1` bo'ladi, NAT ortida esa
    # butun bino uchun bitta. Mashinani aniqlaydigan yagona qiymat -
    # clientning o'zi aytgan LAN manzili (handshake'da yuboriladi).
    # U ISHONCHSIZ, lekin bu yerda hech qanday ruxsat qarori
    # qabul qilinmaydi - faqat yozib qo'yiladi.
    lan_ip = getattr(device, "reported_lan_ip", None)
    session = ExamSession.objects.create(
        pinfl=pinfl,
        last_name=pending.get("last_name", ""),
        first_name=pending.get("first_name", ""),
        middle_name=pending.get("middle_name", ""),
        external_candidate_id=pending.get("external_candidate_id", ""),
        # Test havolasi JSHSHIR tekshiruvida olingan va SHU YERDA
        # muzlatiladi — `exam/access/` uni qayta so'ramaydi.
        external_test_link_enc=encrypt(pending.get("external_test_link", "")) or "",
        external_status=(pending.get("external_status") or "")[:32],
        # Platformaning javobi DALIL sifatida saqlanadi: apellyatsiyada
        # "nega bu talabgor kiritilgan?" degan savolga javob beradi.
        meta={
            "seat": pending.get("seat"),
            "platform": {
                "message": pending.get("platform_message", ""),
                "is_finished": bool(pending.get("platform_is_finished")),
                "abitur_id": pending.get("external_abitur_id", ""),
                "duration_minutes": int(pending.get("duration_minutes") or 0),
            },
            # UCHTA MANZIL, UCHTA MA'NO va ularni aralashtirmaslik
            # kerak - bayonnomada har biri boshqa savolga javob
            # beradi:
            #   lan     - talabgor qaysi MASHINADA o'tirgan;
            #   source  - server so'rovni qaysi manzildan ko'rgan
            #             (NAT ortida butun bino uchun bitta);
            #   public  - bino qaysi tashqi manzil bilan chiqadi.
            "network": {
                "lan_ip": lan_ip or "",
                "source_ip": ip_address or "",
                "public_ip": getattr(device, "reported_public_ip", "") or "",
            },
        },
        external_access_from=_parse_dt(pending.get("external_access_from")),
        external_access_until=_parse_dt(pending.get("external_access_until")),
        reference_embedding=reference_embedding,
        # Imtihondan 90 kun keyin PII anonimlashtiriladi.
        anonymize_after=timezone.now() + timezone.timedelta(days=90),
        exam=exam,
        schedule_id=pending.get("schedule_id"),
        computer=computer,
        zone=zone,
        device=device,
        attempt_no=(last_attempt or 0) + 1,
        exam_date=exam_date,
        status=ExamSession.Status.READY,
        ip_address=lan_ip or ip_address or None,
        mac_address=computer.mac_address if computer is not None else "",
        machine_uuid=(computer.machine_uuid or "") if computer is not None else "",
        last_heartbeat_at=timezone.now(),
    )
    logger.info("Sessiya yaratildi: %s (urinish %s)", session.public_id, session.attempt_no)
    _replace_previous_on_device(session)
    return session


def _replace_previous_on_device(session: ExamSession) -> None:
    """
    Shu mashinadagi oldingi ochiq sessiyani DARHOL yopadi va bog'laydi.

    Client qulab qayta ishga tushsa, operator JSHSHIR va yuz
    tekshiruvidan qayta o'tadi va yangi urinish yaratiladi (tokenni
    diskda saqlamaslik — ataylab). Eskisi esa `close_stale_sessions`
    gacha (`STALE_SESSION_AFTER`) "jarayonda" turardi, va bu uch muammo
    berardi:
      * panelda bitta talabgorning ikkita faol sessiyasi;
      * eskisi yopilganda `_release` "bitta talabgor - bitta sessiya"
        qulfini o'chirardi - egasi qurilma, ya'ni ikkalasida BIR XIL,
        va yangi sessiya qulfsiz qolardi;
      * proktor ikki urinish bog'liqligini ko'rmasdi (FaceID xatolari
        hisoblagichi yangisida noldan boshlanadi).

    Shuning uchun qulfga TEGILMAYDI: u endi yangi sessiyaniki. Boshqa
    mashinadagi sessiya bu yerga yetmaydi - uni `lookup_candidate`
    (`SessionAlreadyActive`) oldinroq to'xtatadi.
    """
    if session.device_id is None:
        return
    previous = (
        ExamSession.objects.select_for_update()
        .filter(
            pinfl=session.pinfl,
            exam_id=session.exam_id,
            exam_date=session.exam_date,
            device_id=session.device_id,
        )
        .exclude(pk=session.pk)
        .exclude(status__in=ExamSession.TERMINAL_STATUSES)
        .order_by("-attempt_no")
        .first()
    )
    if previous is None:
        return

    _flush_counters(previous)
    previous.status = ExamSession.Status.EXPIRED
    previous.finished_at = timezone.now()
    previous.meta = {**(previous.meta or {}), "replaced_by": str(session.public_id)}
    previous.save(
        update_fields=[
            "status", "finished_at", "meta", "event_count", "screenshot_count",
            "face_fail_count", "face_check_count", "risk_score", "updated_at",
        ]
    )
    _complete_proctoring(previous, reason="replaced")
    # `_release` EMAS: u qulfni ham olib tashlardi.
    session_state.revoke_session_token(previous.token_hash)
    session_state.clear_state(previous.pk, previous.zone_id)
    _broadcast_status(previous)

    session.meta = {**(session.meta or {}), "previous_session": str(previous.public_id)}
    session.save(update_fields=["meta", "updated_at"])
    logger.info(
        "Oldingi sessiya %s yangisi bilan almashtirildi: %s",
        previous.public_id, session.public_id,
    )


def _log_face_attempt(*, pinfl: str, faces_detected: int, reason: str) -> None:
    """Sessiyasiz muvaffaqiyatsiz urinish — sessiya hali yaratilmagan."""
    logger.info(
        "Kirishdagi FaceID rad etildi: pinfl=%s sabab=%s yuzlar=%s",
        mask_pinfl(pinfl), reason, faces_detected,
    )


# --------------------------------------------------------------------------
# 3-qadam: sessiya tokeni + tashqi platformaga kirish
# --------------------------------------------------------------------------
def issue_session_token(session: ExamSession) -> str:
    """
    Opaque sessiya tokeni (JWT emas).

    Ochiq token faqat shu yerda mavjud; DB va Redis'da uning HMAC hash'i
    saqlanadi. Redis dump'i sizib chiqsa, faol sessiyalarni o'g'irlab
    bo'lmaydi.
    """
    raw_token = generate_token(32)
    digest = hash_token(raw_token)
    ttl = settings.PROCTORING["SESSION_TOKEN_TTL"]

    session.token_hash = digest
    session.token_expires_at = timezone.now() + timezone.timedelta(seconds=ttl)
    session.save(update_fields=["token_hash", "token_expires_at", "updated_at"])

    session_state.store_session_token(
        token_hash=digest,
        payload={
            "session_id": session.pk,
            "public_id": str(session.public_id),
            "exam_id": session.exam_id,
            "device_id": session.device_id,
            "zone_id": session.zone_id,
            "status": session.status,
        },
        ttl=ttl,
    )
    return raw_token


def issue_exam_access(session: ExamSession, *, ip_address: str = "") -> dict:
    """
    Tashqi platformaga kirish havolasi (`data.test_link`).

    Havola JSHSHIR tekshiruvida olingan va sessiyaga muzlatilgan;
    bu yerda u faqat deshifrlanadi. Token havolaning ICHIDA va uni
    platformaning o'zi shunday bergan — ya'ni uni cookie yoki POST
    body'ga ko'chirish mumkin emas: platforma uni URL'dan kutadi.

    Shaxs tasdig'i AYNAN SHU YERDA to'siladi: bu — qaytib bo'lmaydigan
    nuqta. Undan keyin talabgor tashqi platformada test topshira
    boshlaydi va aynan shu sabab havola JSHSHIR tekshiruvida
    berilmaydi (u yerda berilsa, FaceID'ni chetlab o'tish mumkin
    bo'lardi).
    """
    if settings.PROCTORING["REQUIRE_IDENTITY_CONFIRMATION"] and not session.identity_verified:
        raise IdentityNotConfirmed()

    test_link = session.external_test_link
    if not test_link:
        # Lookup paytida havola kelmagan bo'lsa sessiya umuman
        # yaratilmasligi kerak edi — bu holat kelib chiqsa, muammo bizda.
        logger.error(
            "Sessiya %s da test havolasi yo'q", session.public_id
        )
        raise ExternalPlatformError(
            "Test havolasi topilmadi — talabgorni qaytadan tekshiring"
        )

    if not session.external_access_open:
        raise ExamNotOpen(
            "Tashqi platforma bu talabgorga hozir kirishga ruxsat bermayapti"
        )

    if session.external_status in _CLOSED_PLATFORM_STATUSES:
        raise ExamNotOpen(
            f"Test tashqi platformada allaqachon yakunlangan ({session.external_status})"
        )

    if session.status == ExamSession.Status.READY:
        session.status = ExamSession.Status.IN_PROGRESS
        session.started_at = timezone.now()
        session.save(update_fields=["status", "started_at", "updated_at"])

    logger.info(
        "WebView ochildi: session=%s ip=%s", session.public_id, ip_address or "-"
    )

    remaining = None
    if session.external_access_until:
        remaining = max(
            0, int((session.external_access_until - timezone.now()).total_seconds())
        )

    return {
        # Platforma bergan to'liq havola — token uning ichida.
        "login_url": test_link,
        # `url` — havola tayyor, client uni shunchaki ochadi.
        # Eski `post`/`cookie` yo'llari bu platformada ishlamaydi:
        # token URL'da va uni body'ga ko'chirish platformani
        # tanimaydigan holga keltirardi.
        "delivery": "url",
        "platform_access_until": session.external_access_until,
        "platform_access_seconds_left": remaining,
        # Allowlist AYNAN OCHILADIGAN havoladan olinadi, `site_url`
        # dan EMAS: `site_url` endi API manzili (`api.test.uz`), test
        # esa boshqa domenda ochilishi mumkin (`test.uz`). Eski
        # manbani qoldirish WebView'da butun sahifani bloklardi.
        "allowed_domains": _link_domains(test_link, session.exam),
        # `site_header` client'ga BERILMAYDI. U platforma API'sining
        # kredensiali va serverda qoladi: 500 mashinaga tarqalgan
        # token bekor ham qilinmaydi, kuzatilmaydi ham. Platformaga
        # so'rovni faqat backend yuboradi (`integrations/exam_site.py`).
    }


def _link_domains(test_link: str, exam) -> list:
    """
    WebView allowlist'i: test havolasining domeni.

    Imtihon manzili (`site_url`) ham qo'shiladi: platforma test
    sahifasidan o'z API'siga so'rov qilishi mumkin va u bloklansa
    sahifa yarim ishlagan holda qolardi. Ikkalasi bir xil bo'lsa
    ro'yxatda bir marta turadi.
    """
    from urllib.parse import urlparse

    domains = []
    for candidate in (urlparse(test_link).hostname, *exam.get_allowed_domains()):
        if candidate and candidate not in domains:
            domains.append(candidate)
    return domains


# --------------------------------------------------------------------------
# Davriy yuz tekshiruvi
# --------------------------------------------------------------------------
def verify_periodic_face(
    *,
    session: ExamSession,
    score: int | None,
    faces_detected: int,
    image: bytes | None = None,
    passed_since_last: int = 0,
    config: dict,
    occurred_at=None,
) -> dict:
    """
    Test davomidagi yuz tekshiruvi — FAQAT MUVAFFAQIYATSIZ NATIJA.

    SOLISHTIRISH CLIENTDA. Etalon ham (kirishda olingan vektor), jonli
    kadr ham o'sha yerda; cosine bir juft 512 o'lchamli vektor uchun
    ~5 µs va uni tarmoq orqali haydashning ma'nosi yo'q. Ilgari
    embedding har tekshiruvda serverga kelardi — 10 000 talaba × 6
    tekshiruv/daqiqa = 1000 so'rov/sekund, ularning 99% i esa "hammasi
    joyida" degan xabar edi.

    Endi client faqat MOS KELMAGANDA murojaat qiladi va u bilan birga
    o'sha paytdagi KADRni yuboradi — "nega mos kelmadi?" degan savolga
    javob beradigan yagona narsa shu.

    IKKI HISOBLAGICH, IKKI EGASI:

        face_checks  -> CLIENT (heartbeat, `hset`). U barcha
                        tekshiruvlarni ko'radi, server esa faqat
                        muvaffaqiyatsizlarini. Server sanaganda toza
                        sessiyada "0 tekshiruv" chiqib, kuzatuv
                        ishlamagandek ko'rinardi.
        face_fails   -> SERVER (`incr`). Chetlashtirish qarori shunga
                        tayanadi va u atomik bo'lishi shart.

    `passed_since_last` — oxirgi xabardan keyingi MUVAFFAQIYATLI
    tekshiruvlar soni. Usiz "ketma-ket" qoidasini qo'llab bo'lmasdi:
    server oradagi muvaffaqiyatlarni ko'rmaydi va ikki soat oralab
    kelgan uchta xato chegaraga yetib qolardi.

    CHEGARAGA YETISH — CHETLASHTIRISH EMAS. Ilgari `max_fail` ga
    yetganda sessiya AVTOMATIK tugatilardi va talabgor imtihondan
    chiqib qolardi. Endi bu faqat XABAR: `high_suspicion_identity`
    kritik hodisasi tug'iladi va u panelga darhol yetadi (kritik
    hodisalar write-behind emas). Qarorni PROKTOR qabul qiladi —
    u kadrni va dalil rasmlarini ko'rib turibdi, client esa faqat
    ballni biladi. Yorug'lik o'zgarishi yoki ko'zoynak tufayli
    ketma-ket uchta past ball butun imtihonni bekor qilishi mumkin
    emas edi.
    """
    from apps.proctoring.services import face_images

    occurred_at = occurred_at or timezone.now()
    threshold = int(config["face"]["min_score_exam"])
    score = _clamp_score(score)
    passed_since_last = max(0, int(passed_since_last or 0))

    # Ball CLIENTNIKI (`source=client`). Server uni qayta hisoblay
    # olmaydi: buning uchun rasmdan embedding olish, ya'ni serverda
    # ML runtime kerak — arxitektura esa ataylab boshqacha
    # (`services/face_images.py` docstring'i).
    passed = bool(score >= threshold and faces_detected == 1)

    # `session.exam_id` — `session.exam` EMAS: ikkinchisi har
    # muvaffaqiyatsiz tekshiruvda ortiqcha SELECT qilardi.
    image_path, image_purge_after = _store_face_image(
        image, exam_id=session.exam_id, session=session, config=config
    )
    try:
        log_row = FaceVerificationLog.objects.create(
            session=session,
            exam_id=session.exam_id,
            zone_id=session.zone_id,
            pinfl=session.pinfl or "",
            stage=FaceVerificationLog.Stage.PERIODIC,
            source=FaceVerificationLog.Source.CLIENT,
            score=score,
            threshold=threshold,
            passed=passed,
            faces_detected=faces_detected,
            image_path=image_path,
            image_purge_after=image_purge_after,
            occurred_at=occurred_at,
        )
    except Exception:
        face_images.discard(image_path)
        raise

    fail_count = 0
    if passed_since_last:
        # Oradagi muvaffaqiyatli tekshiruvlar zanjirni UZADI. Bitta
        # tasodifiy xato (yorug'lik o'zgardi, bosh burildi) talabgorni
        # chetlashtirmasligi kerak.
        session_state.reset_counter(session.pk, "face_fails")

    if not passed:
        fail_count = session_state.increment(session.pk, "face_fails")
        session_state.bump_risk(session.pk, 8)

        event_type = (
            ProctoringEvent.Type.MULTIPLE_FACES
            if faces_detected > 1
            else ProctoringEvent.Type.FACE_NOT_FOUND
            if faces_detected == 0
            else ProctoringEvent.Type.FACE_MISMATCH
        )
        from apps.proctoring.services.ingest import push_event

        push_event(
            session_id=session.pk,
            zone_id=session.zone_id,
            type=event_type,
            severity=ProctoringEvent.Severity.HIGH,
            occurred_at=occurred_at,
            # `face_log_id` — hodisadan rasmga o'tish uchun yagona
            # ko'prik. FK QO'YILMAYDI: hodisa jadvali partitsiyalangan
            # va unga FK `bulk_create` ni buzadi (`EvidenceArtifact`
            # bilan bir xil sabab).
            payload={
                "score": score,
                "threshold": threshold,
                "faces": faces_detected,
                "face_log_id": log_row.pk,
            },
        )
    else:
        session_state.reset_counter(session.pk, "face_fails")

    max_fail = int(config["face"]["max_fail"])
    # AYNAN CHEGARAGA YETGANDA bir marta. Undan keyingi har bir
    # muvaffaqiyatsizlik yana kritik hodisa bergani panelni bir xil
    # xabar bilan to'ldirardi va proktor uni o'qishni to'xtatardi;
    # tarkibiy `face_mismatch` hodisalari esa avvalgidek kelaveradi.
    limit_reached = fail_count == max_fail
    if limit_reached:
        _notify_face_limit(
            session=session,
            fail_count=fail_count,
            max_fail=max_fail,
            score=score,
            threshold=threshold,
            occurred_at=occurred_at,
            log_id=log_row.pk,
        )

    return {
        "passed": passed,
        "score": score,
        "threshold": threshold,
        "fail_count": fail_count,
        "max_fail": max_fail,
        # Client bu qiymatga QARAB HECH NARSA QILMAYDI (imtihon
        # to'xtamaydi) — u faqat holat qatorida ko'rsatiladi.
        # Chetlashtirish proktorning ochiq amali bo'lib qoladi.
        "limit_reached": limit_reached,
    }


def _notify_face_limit(
    *, session, fail_count, max_fail, score, threshold, occurred_at, log_id
) -> None:
    """
    Ketma-ket muvaffaqiyatsizliklar chegarasi — PANELGA xabar.

    `high_suspicion_identity` turi ATAYLAB tanlangan (yangi tur
    kiritilmadi): u allaqachon "shaxs almashtirilgan" degan xulosani
    bildiradi va frontendda ham tarjimasi, ham turkumi bor
    (`utils/labels.js`, `utils/events.js`). Ketma-ket N marta yuz mos
    kelmasligi aynan shu xulosaga olib keladi — faqat manba boshqa
    (fusion emas, davriy tekshiruv), va u `payload.source` da yozilgan.

    Kritik jiddiylik SHART: kritik hodisalar write-behind buferidan
    o'tmasdan darhol DB'ga yoziladi va proktor ekranida bir necha
    soniyada emas, o'sha zahoti ko'rinadi.
    """
    from apps.proctoring.services.ingest import push_event

    push_event(
        session_id=session.pk,
        zone_id=session.zone_id,
        type=ProctoringEvent.Type.HIGH_SUSPICION_IDENTITY,
        severity=ProctoringEvent.Severity.CRITICAL,
        occurred_at=occurred_at,
        payload={
            "source": "periodic_face",
            "fail_count": fail_count,
            "max_fail": max_fail,
            "score": score,
            "threshold": threshold,
            "face_log_id": log_id,
        },
    )
    logger.warning(
        "FaceID chegarasiga yetildi: session=%s %s/%s (ball %s, talab %s) — "
        "sessiya TO'XTATILMADI, qaror proktorda",
        session.public_id, fail_count, max_fail, score, threshold,
    )


# --------------------------------------------------------------------------
# Yakunlash
# --------------------------------------------------------------------------
def _complete_proctoring(session: ExamSession, *, reason: str) -> None:
    """
    Sessiya yakunlanganda kuzatuv ham yakunlanadi.

    Alohida chaqiruv, chunki yakunlash uch yo'ldan keladi (operator,
    proktor chetlashtirishi, `close_stale_sessions`) va uchalasida
    ham holat `completed` bo'lishi kerak. Aks holda yakunlangan
    sessiya `active` bo'lib qolar va dalil qabul qilinaverardi.

    Xato YUTILADI: kuzatuv holatini yozib bo'lmagani imtihonni
    yakunlashni to'xtatmasligi kerak - yakunlanmagan sessiya ancha
    qimmatroq muammo.
    """
    from apps.proctoring.services import proctoring as proctoring_service

    try:
        proctoring_service.stop(session, reason=reason)
    except Exception:
        logger.exception("Kuzatuv holatini yakunlab bo'lmadi: %s", session.public_id)


@transaction.atomic
def finish_session(
    session: ExamSession, *, reason: str = "", completed: bool = False
) -> ExamSession:
    """
    Imtihonni yakunlaydi.

    `completed` — talabgor testni O'ZI yakunladi (clientdagi «Yakunlash»
    tugmasi). Faqat shunda kompyuter broni bo'shaydi va joy keyingi
    talabgorga beriladi; dasturdan chiqishdagi yakun (`completed`
    yo'q) joyni band qoldiradi (`bookings.release_after_session`).

    Bo'shatish YAKUN BILAN BITTA TRANZAKSIYADA: alohida qadam bo'lsa
    va u yiqilsa, client qayta urina olmasdi — sessiya tokeni yakunda
    bekor bo'ladi. Natija `meta.seat_release` ga yoziladi: bayonnomada
    "joy qachon bo'shatildi" degan savolga javob.
    """
    if session.status in ExamSession.TERMINAL_STATUSES:
        return session

    _flush_counters(session)
    session.status = ExamSession.Status.FINISHED
    session.finished_at = timezone.now()
    update_fields = [
        "status", "finished_at", "event_count", "screenshot_count",
        "face_fail_count", "face_check_count", "risk_score", "updated_at",
    ]
    if completed and _release_seat(session, by="finish"):
        update_fields.append("meta")
    session.save(update_fields=update_fields)
    _complete_proctoring(session, reason=reason or "finished")
    _release(session)
    _broadcast_status(session)
    _notify_external(session, "finished", {"reason": reason})
    return session


def _release_seat(session: ExamSession, *, by: str) -> bool:
    """
    Kompyuter bronini bo'shatadi va izini `meta.seat_release` ga yozadi.

    Chaqiruvchi `meta` ni saqlaydi (o'zining `update_fields` i bilan).
    `True` — joy bo'shatildi.
    """
    from apps.exams import bookings

    released = bookings.release_after_session(
        schedule_id=session.schedule_id, pinfl=session.pinfl
    )
    if released is None:
        return False
    session.meta = {
        **(session.meta or {}),
        "seat_release": {
            "at": (session.finished_at or timezone.now()).isoformat(),
            "by": by,
            "booking_id": released.pk,
            "seat": bookings.computer_payload(released.computer),
        },
    }
    return True


@transaction.atomic
def terminate_session(
    session: ExamSession, *, actor=None, reason: str = "", release_seat: bool = False
) -> ExamSession:
    """
    Chetlashtirish — DARHOL kuchga kiradi.

    Token Redis'dan o'chiriladi, shuning uchun keyingi so'rov 401 oladi.
    Bu aynan JWT ishlatmaslik sababi.

    `release_seat` — ADMINISTRATOR chetlashtirdi (panel): kompyuter
    broni ham shu tranzaksiyada bo'shaydi. Imtihondagi talabgorning
    joyini panelda qo'lda bo'shatib bo'lmaydi (`SeatInUse`), ya'ni
    chetlashtirish uning YAGONA yo'li. Client'dagi "shaxs rad etildi"
    (`reject_identity`) uni bermaydi — u administrator qarori emas.
    """
    if session.status in ExamSession.TERMINAL_STATUSES:
        return session

    _flush_counters(session)
    session.status = ExamSession.Status.TERMINATED
    session.finished_at = timezone.now()
    session.terminated_by = actor
    session.termination_reason = reason[:500]
    update_fields = [
        "status", "finished_at", "terminated_by", "termination_reason",
        "event_count", "screenshot_count", "face_fail_count",
        "face_check_count", "risk_score", "updated_at",
    ]
    if release_seat and _release_seat(session, by="terminate"):
        update_fields.append("meta")
    session.save(update_fields=update_fields)

    ProctoringEvent.objects.create(
        session=session,
        type=ProctoringEvent.Type.SESSION_TERMINATED,
        severity=ProctoringEvent.Severity.CRITICAL,
        occurred_at=timezone.now(),
        payload={"reason": reason, "actor": getattr(actor, "username", "system")},
    )

    _complete_proctoring(session, reason=reason or "terminated")
    _release(session)
    _broadcast_status(session, reason=reason)
    _notify_external(session, "terminated", {"reason": reason})
    return session


def expire_session(session: ExamSession) -> ExamSession:
    """Heartbeat kelmay qolgan sessiya (client o'lgan yoki tarmoq uzilgan)."""
    _flush_counters(session)
    session.status = ExamSession.Status.EXPIRED
    session.finished_at = timezone.now()
    session.save(
        update_fields=[
            "status", "finished_at", "event_count", "screenshot_count",
            "face_fail_count", "face_check_count", "risk_score", "updated_at",
        ]
    )
    _complete_proctoring(session, reason="expired")
    _release(session)
    _broadcast_status(session)
    return session


def _broadcast_status(session: ExamSession, **fields) -> None:
    """Dashboard'ga holat o'zgarishini yetkazadi (xatosi oqimni to'xtatmaydi)."""
    from apps.proctoring.services.realtime import broadcast_session_update

    broadcast_session_update(session, **fields)


def _flush_counters(session: ExamSession) -> None:
    """Redis hisoblagichlarini yakuniy holatga ko'chiradi."""
    hot = session_state.get_state(session.pk)
    session.event_count = int(hot.get("events", session.event_count) or 0)
    session.screenshot_count = int(hot.get("shots", session.screenshot_count) or 0)
    session.face_fail_count = int(hot.get("face_fails", session.face_fail_count) or 0)
    session.face_check_count = int(hot.get("face_checks", session.face_check_count) or 0)
    session.risk_score = min(100, int(hot.get("risk", session.risk_score) or 0))


def _release(session: ExamSession) -> None:
    session_state.revoke_session_token(session.token_hash)
    session_state.clear_state(session.pk, session.zone_id)
    if session.pinfl:
        session_state.unlock_candidate(
            session.pinfl, session.exam_id, f"dev:{session.device_id or 'na'}"
        )


def _notify_external(session: ExamSession, status: str, meta: dict) -> None:
    """
    Tashqi platformaga xabar — KRITIK YO'LDA EMAS.

    Celery orqali ketadi; talabgor tashqi API javobini kutmaydi.
    """
    from apps.proctoring.tasks import report_session_result

    try:
        report_session_result.delay(str(session.public_id), status, meta)
    except Exception as exc:
        # Broker tushgan bo'lsa ham sessiya yakunlanishi kerak.
        logger.warning("Natijani navbatga qo'yib bo'lmadi: %s", exc)
