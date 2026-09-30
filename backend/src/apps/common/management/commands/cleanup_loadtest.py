"""
`seed_loadtest` yaratgan hamma narsani va sinov davomida tug'ilgan
yozuvlarni O'CHIRADI (idempotent).

    python manage.py cleanup_loadtest --allow-db proctoring_loadtest            # quruq yurish
    python manage.py cleanup_loadtest --allow-db proctoring_loadtest --yes      # haqiqatan
    python manage.py cleanup_loadtest --allow-db proctoring_loadtest --throttle-only --yes

Faqat `LT` belgili yozuvlar: viloyat `dtm_id=990001`, uning binolari
va kompyuterlari, `lt_` foydalanuvchilar, `LT Yuklama imtihoni` va shu
obyektlarga bog'langan sessiyalar. Boshqa ma'lumotga tegilmaydi.

TARTIB (CLAUDE.md: "o'chirish: avval fayl, keyin qator"):

1. Fayllar storage INTERFEYSI orqali (`screenshot_delete`,
   `evidence.delete`, `face_images.discard`) — `os.unlink` emas.
2. Hodisalar (`proctoring_event` — partitsiyalangan, FK emas yo'llar bor),
   sessiyalar (CASCADE: skrinshot/dalil/yozuv/texnik muammo qatorlari),
   FaceID jurnali (sessiyasizlari ham — `pinfl` bo'yicha).
3. Bron, jadval, imtihon, qurilma, kompyuter, bino, IP, audit, xodimlar,
   viloyat — HARD delete (`SoftDeleteModel` ning `.delete()` i faqat
   `deleted_at` qo'yadi, sinov qoldig'i bazada qolib ketardi).
4. Redis: sessiya holati/tokenlar, presence, kamera tekshiruvi,
   throttle hisoblagichlari.

OGOHLANTIRISH: Celery ingest ishlab turgan paytda chaqiring — Redis
oqimida qolgan LT hodisalari keyinroq yozilib, o'chirilgan sessiyaga
ishora qilardi (FK yiqilib `:dead` oqimiga tushadi, zarar yo'q, lekin
shovqin). Tozalashdan oldin 10-15 s kuting.
"""

from __future__ import annotations

from django.core.cache import cache
from django.core.management import BaseCommand, CommandError
from django.db import connection, transaction

from apps.common.management.commands.seed_loadtest import (
    DEVICE_PREFIX,
    EXAM_NAME,
    EXAM_TYPE_KEY,
    PINFL_PREFIX,
    REGION_DTM_ID,
    USER_PREFIX,
)


class Command(BaseCommand):
    help = "Yuklama sinovi ma'lumotini (LT) to'liq o'chiradi"

    def add_arguments(self, parser):
        parser.add_argument("--allow-db", default="", help="Himoya: bazaning nomi")
        parser.add_argument("--yes", action="store_true", help="Haqiqatan o'chirish")
        parser.add_argument("--throttle-only", action="store_true",
                            help="Faqat throttle hisoblagichlarini tozalash")
        parser.add_argument("--keep-seed", action="store_true",
                            help="Sinov IZLARINI (sessiya, fayl, audit, Redis) o'chiradi, "
                                 "seed ma'lumotini (kompyuter, xodim, imtihon) qoldiradi")

    def handle(self, *args, **opts):
        db_name = connection.settings_dict.get("NAME")
        if opts["allow_db"] != db_name:
            raise CommandError(f"Himoya: joriy baza '{db_name}'. `--allow-db {db_name}` bering.")

        if opts["throttle_only"]:
            n = self._throttle_keys(opts["yes"])
            self.stdout.write(f"Throttle kalitlari: {n}")
            return

        from apps.devices.models import Computer, DeviceToken
        from apps.exams.models import Exam
        from apps.proctoring.models import ExamSession, FaceVerificationLog
        from apps.regions.models import Region
        from apps.users.models import User

        region = Region.objects.filter(dtm_id=REGION_DTM_ID).first()
        exams = list(Exam.objects.filter(name=EXAM_NAME).values_list("pk", flat=True))
        computers = list(
            Computer.objects.filter(zone__region=region).values_list("pk", flat=True)
        ) if region else []
        sessions = ExamSession.objects.filter(exam_id__in=exams) | ExamSession.objects.filter(
            computer_id__in=computers
        )
        session_ids = list(sessions.values_list("pk", flat=True).distinct())
        users = list(User.objects.filter(username__startswith=USER_PREFIX).values_list("pk", flat=True))
        devices = list(
            DeviceToken.objects.filter(device_id__startswith=DEVICE_PREFIX).values_list("device_id", flat=True)
        )
        face_logs = FaceVerificationLog.objects.filter(pinfl__startswith=PINFL_PREFIX)

        self.stdout.write(
            f"Baza: {db_name}\n  sessiyalar: {len(session_ids)}\n  FaceID jurnali: {face_logs.count()}\n"
            f"  kompyuterlar: {len(computers)}\n  xodimlar: {len(users)}\n  qurilmalar: {len(devices)}"
        )
        if not opts["yes"]:
            self.stdout.write(self.style.WARNING("Quruq yurish. O'chirish uchun --yes bering."))
            return

        files = self._delete_files(session_ids, face_logs)
        self._delete_rows(session_ids, face_logs, users, region, exams, keep_seed=opts["keep_seed"])
        keys = self._redis(session_ids, devices)
        throttles = self._throttle_keys(True)
        self.stdout.write(self.style.SUCCESS(
            f"Tayyor: {files} fayl, {len(session_ids)} sessiya, {keys} Redis kaliti, "
            f"{throttles} throttle kaliti o'chirildi"
            + (" (seed ma'lumoti qoldirildi)" if opts["keep_seed"] else "")
        ))

    # ------------------------------------------------------------------
    def _delete_files(self, session_ids, face_logs) -> int:
        from apps.proctoring.models import EvidenceArtifact, ProctoringScreenshot
        from apps.proctoring.services import evidence as evidence_service
        from apps.proctoring.services import face_images
        from apps.proctoring.services.screenshots import screenshot_delete

        removed = 0
        for shot in ProctoringScreenshot.objects.filter(session_id__in=session_ids).iterator():
            removed += int(bool(screenshot_delete(shot)))
        for artifact in EvidenceArtifact.objects.filter(session_id__in=session_ids).iterator():
            removed += int(bool(evidence_service.delete(artifact)))
        for log in face_logs.iterator():
            for path in (log.image_path, log.reference_image_path):
                if path:
                    removed += int(bool(face_images.discard(path)))
        return removed

    @transaction.atomic
    def _delete_rows(self, session_ids, face_logs, users, region, exams, *, keep_seed: bool):
        from apps.controls.models import AllowedPublicIp
        from apps.devices.models import Computer, DeviceToken
        from apps.exams.models import ComputerBooking, Exam, ExamSchedule, ExamType
        from apps.proctoring.models import AuditLog, ExamSession, ProctoringEvent
        from apps.regions.models import Zone
        from apps.users.models import User

        ProctoringEvent.objects.filter(session_id__in=session_ids).delete()
        face_logs.delete()
        ExamSession.objects.filter(pk__in=session_ids).delete()
        AuditLog.objects.filter(actor_id__in=users).delete()
        AuditLog.objects.filter(actor_username__startswith=USER_PREFIX).delete()
        if keep_seed:
            return
        ComputerBooking.objects.filter(schedule__exam_id__in=exams).delete()
        ExamSchedule.objects.filter(exam_id__in=exams).hard_delete()
        Exam.objects.filter(pk__in=exams).hard_delete()
        ExamType.objects.filter(key=EXAM_TYPE_KEY).hard_delete()
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

            OutstandingToken.objects.filter(user_id__in=users).delete()
        except Exception:  # pragma: no cover
            pass
        User.objects.filter(pk__in=users).delete()
        DeviceToken.objects.filter(device_id__startswith=DEVICE_PREFIX).delete()
        if region is not None:
            ComputerBooking.objects.filter(computer__zone__region=region).delete()
            Computer.objects.filter(zone__region=region).hard_delete()
            AllowedPublicIp.objects.filter(zone__region=region).delete()
            Zone.objects.filter(region=region).hard_delete()
            region.delete()
        AllowedPublicIp.objects.filter(ip_address__startswith="100.64.").filter(
            name__startswith="LT "
        ).delete()
        cache.clear()

    def _redis(self, session_ids, devices) -> int:
        from apps.common.redis_client import get_redis
        from apps.proctoring.services import risk, state

        client = get_redis()
        keys = []
        for sid in session_ids:
            keys.append(state.state_key(sid))
            keys.append(risk.breakdown_key(sid))
        for device_id in devices:
            keys += [f"dev:online:{device_id}", f"dev:online:db:{device_id}", f"cam:check:{device_id}"]
        removed = 0
        for start in range(0, len(keys), 500):
            removed += client.delete(*keys[start:start + 500])
        # Cooldown kalitlari TTL bilan o'zi so'nadi; ular hodisa turi
        # bo'yicha — naqsh bilan olinadi.
        prefix = risk.cooldown_key(0, "x").split(":0:", 1)[0]
        sid_text = {str(s) for s in session_ids}
        for key in client.scan_iter(match=f"{prefix}:*", count=1000):
            parts = (key.decode("utf-8", "ignore") if isinstance(key, bytes) else key).split(":")
            if len(parts) >= 3 and parts[-2] in sid_text:
                removed += client.delete(key)
        if session_ids:
            client.srem(state.dirty_set_key(), *session_ids)
        # Tokenlar hash bo'yicha saqlanadi — sessiya ID si qiymat ichida.
        sid_set = {str(s) for s in session_ids}
        for key in client.scan_iter(match="sess:tok:*", count=1000):
            raw = client.get(key) or ""
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            marker = raw.split('"session_id":', 1)[-1].split(",", 1)[0].strip()
            if marker in sid_set:
                removed += client.delete(key)
        return removed

    def _throttle_keys(self, apply: bool) -> int:
        """DRF throttle hisoblagichlari (kesh bazasida, `throttle_<scope>_<ident>`)."""
        try:
            keys = cache.keys("throttle_*")
        except Exception:
            return 0
        if apply and keys:
            cache.delete_many(keys)
        return len(keys)
