"""
Dalil: kadr va video klip.

Skrinshotdan farqli o'laroq bu yerda IKKI xil fayl bor va ular
BOSHQACHA tekshiriladi. Rasm Pillow bilan to'liq ochiladi, video
esa faqat sehrli baytlar bo'yicha - serverda ffmpeg yo'q. Shuning
uchun asosiy testlar aynan shu chegarani qamrab oladi: `.mp4`
niqobidagi HTML o'tmasligi va tekshiruv KENGAYTMAGA emas,
BAYTLARGA tayanishi kerak.

Ikkinchi mavzu - saqlash muddati. Klip kadrdan ~10 barobar katta va
ular bir xil muddat bilan saqlansa, disk klip hisobiga to'lib
kadrlarni ham birga olib ketardi.
"""

import io
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.common.screenshot_storage import get_screenshot_storage
from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import EvidenceArtifact
from apps.proctoring.services import evidence as evidence_service
from apps.proctoring.tests import factories


def image_bytes(fmt="JPEG", size=(320, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format=fmt)
    return buffer.getvalue()


def mp4_bytes(payload_size: int = 512) -> bytes:
    """
    Eng kichik "haqiqiy" MP4 sarlavhasi.

    To'liq konteyner YASALMAYDI: server ham uni ochmaydi (ffmpeg
    yo'q), ya'ni test tekshiruvdan qattiqroq bo'lishi ma'nosiz
    bo'lardi.
    """
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * payload_size


def webm_bytes(payload_size: int = 512) -> bytes:
    return b"\x1a\x45\xdf\xa3" + b"\x00" * payload_size


def upload(data: bytes, name="evidence.bin", content_type="application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=content_type)


class VideoDetectionTests(TestCase):
    """`_inspect_video` — yagona manba baytlarning o'zi."""

    def test_accepts_mp4(self):
        mime, extension, width, height = evidence_service._inspect_video(mp4_bytes())
        self.assertEqual((mime, extension), ("video/mp4", "mp4"))
        # O'lcham O'QILMAYDI: konteynerni ochish uchun ffmpeg kerak.
        self.assertEqual((width, height), (0, 0))

    def test_accepts_webm(self):
        self.assertEqual(evidence_service._inspect_video(webm_bytes())[0], "video/webm")

    def test_rejects_html_disguised_as_mp4(self):
        """
        Kengaytma ham, `Content-Type` ham CLIENT yozadi.

        Ular ishonchli deb qabul qilinsa, HTML `internal` location'dan
        berilardi va proktorning brauzerida bajarilardi.
        """
        payload = b"<html><script>alert(1)</script></html>" + b" " * 64
        with self.assertRaises(evidence_service.EvidenceRejected):
            evidence_service._inspect_video(payload)

    def test_rejects_avi(self):
        """AVI - haqiqiy video, lekin ro'yxatda yo'q."""
        with self.assertRaises(evidence_service.EvidenceRejected):
            evidence_service._inspect_video(b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 32)

    def test_rejects_tiny_file(self):
        with self.assertRaises(evidence_service.EvidenceRejected):
            evidence_service._inspect_video(b"ftyp")

    def test_frame_goes_through_image_detection(self):
        """
        Kadr uchun RASM tekshiruvi to'liq qayta ishlatiladi.

        Ikkinchi nusxa yozish dekompressiya bombasi himoyasini
        ikkiga bo'lardi va ulardan biri albatta orqada qolardi.
        """
        mime, extension, width, height = evidence_service._inspect(
            image_bytes(), EvidenceArtifact.Kind.FRAME
        )
        self.assertEqual((mime, extension), ("image/jpeg", "jpg"))
        self.assertEqual((width, height), (320, 240))

    def test_video_bytes_rejected_as_frame(self):
        with self.assertRaises(Exception):
            evidence_service._inspect(mp4_bytes(), EvidenceArtifact.Kind.FRAME)


class ReadUploadTests(TestCase):
    def test_clip_limit_is_larger_than_frame_limit(self):
        """
        Klip va kadr ALOHIDA chegaraga ega.

        Bitta chegara ikkalasini ham noto'g'ri qilardi: kadr uchun u
        juda katta (2 MB li "kadr" - bu allaqachon buzilgan client),
        klip uchun juda kichik.
        """
        from django.conf import settings

        conf = settings.PROCTORING["EVIDENCE"]
        self.assertGreater(conf["MAX_CLIP_BYTES"], conf["MAX_FRAME_BYTES"])

    def test_rejects_declared_size_over_limit(self):
        item = upload(b"x" * 10)
        item.size = 999_999_999
        with self.assertRaises(evidence_service.EvidenceTooLarge):
            evidence_service._read_upload(item, EvidenceArtifact.Kind.FRAME)

    def test_rejects_actual_size_over_limit(self):
        """
        `upload.size` ga ISHONMAYMIZ - u `Content-Length` dan keladi.

        "size=10" deb aytib megabayt yuborish mumkin bo'lardi.
        """
        from django.conf import settings

        limit = int(settings.PROCTORING["EVIDENCE"]["MAX_FRAME_BYTES"])
        item = upload(b"x" * (limit + 1_000))
        item.size = 10  # yolg'on
        with self.assertRaises(evidence_service.EvidenceTooLarge):
            evidence_service._read_upload(item, EvidenceArtifact.Kind.FRAME)

    def test_rejects_empty_file(self):
        with self.assertRaises(evidence_service.EvidenceRejected):
            evidence_service._read_upload(upload(b""), EvidenceArtifact.Kind.FRAME)


class PathTests(TestCase):
    def test_layout_separates_kinds(self):
        session = mock.Mock(exam_id=7, pk=42)
        path = evidence_service._build_path(
            session=session,
            kind="clip",
            captured_at=timezone.now(),
            extension="mp4",
            digest="a" * 64,
            attempt=0,
        )
        self.assertTrue(path.startswith("evidence/7/42/clip/"))
        self.assertTrue(path.endswith(".mp4"))

    def test_attempt_changes_name(self):
        """
        Nom to'qnashuvi NORMAL hol.

        Fusion hodisasi kadr va klipni bir lahzada yuboradi; ikkinchi
        urinish boshqa nom olishi kerak, aks holda birinchisi
        ustiga yozilardi.
        """
        session = mock.Mock(exam_id=1, pk=1)
        moment = timezone.now()
        kwargs = dict(
            session=session, kind="frame", captured_at=moment,
            extension="jpg", digest="b" * 64,
        )
        self.assertNotEqual(
            evidence_service._build_path(attempt=0, **kwargs),
            evidence_service._build_path(attempt=1, **kwargs),
        )


class PurgeAfterTests(TestCase):
    def test_clip_and_frame_have_separate_retention(self):
        policy = {"evidence": {"clip_retention_days": 3, "frame_retention_days": 30}}
        clip = evidence_service._purge_after("clip", policy)
        frame = evidence_service._purge_after("frame", policy)
        self.assertLess(clip, frame)

    def test_falls_back_to_settings(self):
        """
        Siyosat yo'q bo'lsa standart muddat.

        `None` qaytarish qatorni ABADIY saqlanadigan qilardi -
        tozalash vazifasi `purge_after` bo'yicha ishlaydi.
        """
        from django.conf import settings

        default = settings.PROCTORING["EVIDENCE"]["CLIP_RETENTION_DAYS"]
        expected = timezone.now() + timedelta(days=default)
        actual = evidence_service._purge_after("clip", None)
        self.assertLess(abs((actual - expected).total_seconds()), 60)

    def test_zero_days_does_not_purge_immediately(self):
        """
        `0` kun - sozlamadagi xato, dalilni DARHOL o'chirish emas.

        Chegara kamida bir kun: aks holda hodisa yozilgan zahoti
        dalil yo'qolardi va uni hech kim ko'rmasdi.
        """
        policy = {"evidence": {"clip_retention_days": 0}}
        self.assertGreater(
            evidence_service._purge_after("clip", policy),
            timezone.now() + timedelta(days=1),
        )


class StoreTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.session = factories.make_session()
        self.storage = get_screenshot_storage()

    def test_stores_frame(self):
        artifact = evidence_service.store(
            session=self.session,
            upload=upload(image_bytes(), name="frame.jpg"),
            kind="frame",
            captured_at=timezone.now(),
            event_type="object_detected",
            camera_role="secondary",
            confidence=91,
        )
        self.assertTrue(self.storage.exists(artifact.file_path))
        self.assertEqual(artifact.mime_type, "image/jpeg")
        self.assertEqual(artifact.event_type, "object_detected")
        self.assertEqual(artifact.camera_role, "secondary")
        self.assertEqual(len(artifact.content_hash), 64)

    def test_stores_clip_with_duration(self):
        artifact = evidence_service.store(
            session=self.session,
            upload=upload(mp4_bytes(), name="clip.mp4"),
            kind="clip",
            captured_at=timezone.now(),
            duration_ms=5200,
        )
        self.assertEqual(artifact.kind, "clip")
        self.assertEqual(artifact.mime_type, "video/mp4")
        self.assertEqual(artifact.duration_ms, 5200)

    def test_path_is_relative_never_absolute(self):
        """
        DB'da FAQAT nisbiy yo'l.

        Absolyut yo'l storage root ko'chganda barcha qatorlarni
        yaroqsiz qilardi va API javobida server katalog
        strukturasini oshkor qilardi.
        """
        artifact = evidence_service.store(
            session=self.session,
            upload=upload(image_bytes()),
            kind="frame",
            captured_at=timezone.now(),
        )
        self.assertFalse(artifact.file_path.startswith("/"))
        self.assertNotIn(":", artifact.file_path)
        self.assertTrue(artifact.file_path.startswith("evidence/"))

    def test_rejects_unknown_kind(self):
        with self.assertRaises(evidence_service.EvidenceRejected):
            evidence_service.store(
                session=self.session,
                upload=upload(image_bytes()),
                kind="thumbnail",
                captured_at=timezone.now(),
            )

    def test_deletes_file_when_row_fails(self):
        """
        YOZISH TARTIBI: avval fayl, keyin qator.

        Qator yozilmasa fayl DARHOL o'chiriladi - aks holda diskda
        hech kim bilmaydigan yetim fayl qolardi.
        """
        with mock.patch.object(
            EvidenceArtifact.objects, "create", side_effect=DatabaseError("boom")
        ):
            with self.assertRaises(DatabaseError):
                evidence_service.store(
                    session=self.session,
                    upload=upload(image_bytes()),
                    kind="frame",
                    captured_at=timezone.now(),
                )

        self.assertEqual(
            EvidenceArtifact.objects.filter(session=self.session).count(), 0
        )

    def test_boxes_are_stored(self):
        boxes = [{"label": "Telefon", "kind": "object", "box": [0.5, 0.75, 0.6, 0.92], "conf": 0.94}]
        artifact = evidence_service.store(
            session=self.session,
            upload=upload(image_bytes()),
            kind="frame",
            captured_at=timezone.now(),
            boxes=boxes,
        )
        self.assertEqual(artifact.boxes, boxes)

    def test_delete_removes_file_before_row(self):
        """
        O'CHIRISH TARTIBI: avval fayl, keyin qator.

        Teskarisida hech kim biladigan yetim fayl qolardi.
        """
        artifact = evidence_service.store(
            session=self.session,
            upload=upload(image_bytes()),
            kind="frame",
            captured_at=timezone.now(),
        )
        path = artifact.file_path
        self.assertTrue(evidence_service.delete(artifact))
        self.assertFalse(self.storage.exists(path))
        self.assertFalse(EvidenceArtifact.objects.filter(pk=artifact.pk).exists())


class EvidenceMarkValidationTests(TestCase):
    """
    Dalil belgilari client'dan keladi va panelda rasm USTIGA chiziladi —
    shuning uchun ular qat'iy tozalanadi, yaroqsizi esa butun dalilni
    emas, faqat o'zini yo'qotadi.
    """

    def _clean(self, boxes):
        from apps.proctoring.api.v1.client_serializers import EvidenceUploadSerializer

        return EvidenceUploadSerializer().validate_boxes(boxes)

    def test_valid_mark_passes_and_extra_keys_are_dropped(self):
        result = self._clean([{
            "label": "Telefon", "kind": "object", "box": [0.5, 0.75, 0.59523, 0.92],
            "conf": 0.93, "html": "<script>",
        }])
        self.assertEqual(result, [{
            "label": "Telefon", "kind": "object", "box": [0.5, 0.75, 0.5952, 0.92], "conf": 0.93,
        }])

    def test_json_string_from_multipart_is_accepted(self):
        import json

        raw = json.dumps([{"label": "Begona odam", "kind": "person", "box": [0, 0, 0.5, 1]}])
        self.assertEqual(self._clean(raw)[0]["kind"], "person")

    def test_legacy_pixel_boxes_are_dropped(self):
        """Eski client: piksel `bbox`, kadr o'lchamisiz — to'g'ri chizib bo'lmaydi."""
        self.assertEqual(self._clean([{"cls": "cell phone", "bbox": [134, 842, 1153, 1511]}]), [])

    def test_coordinates_are_clamped_and_degenerate_dropped(self):
        result = self._clean([
            {"label": "x", "kind": "face", "box": [-0.2, 0.1, 1.7, 0.9]},
            {"label": "bo'sh", "kind": "face", "box": [0.5, 0.5, 0.5, 0.9]},
            {"label": "matn", "kind": "face", "box": ["a", 0, 1, 1]},
        ])
        self.assertEqual(result, [{"label": "x", "kind": "face", "box": [0.0, 0.1, 1.0, 0.9]}])

    def test_unknown_kind_and_long_label_are_normalised(self):
        result = self._clean([{"label": "A" * 200, "kind": "evil", "box": [0, 0, 1, 1], "conf": 7}])
        self.assertEqual(result[0]["kind"], "object")
        self.assertEqual(len(result[0]["label"]), 48)
        self.assertNotIn("conf", result[0])
