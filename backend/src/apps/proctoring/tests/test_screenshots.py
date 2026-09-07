"""
Skrinshotni qabul qilish (fayl tizimi yo'li).

Eng muhim tekshiruv — **fayl turi baytlardan aniqlanadi**. Client
bergan `Content-Type` ham, fayl kengaytmasi ham oddiy satr. `screen.jpg`
nomi ostida HTML yoki SVG kelsa, nginx uni `internal` location'dan
beradi va u proktorning brauzerida ochiladi — ya'ni saqlangan XSS.

Ikkinchi mavzu — yozish tartibi: avval fayl, keyin DB qatori. Qator
yozilmasa fayl darhol o'chiriladi, aks holda diskda hech kim
bilmaydigan yetim fayl qoladi.
"""

import io
from datetime import datetime
from datetime import timezone as dt_timezone
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.common.exceptions import (
    ScreenshotRejected,
    ScreenshotStoreFailed,
    ScreenshotTooLarge,
)
from apps.common.screenshot_storage import get_screenshot_storage
from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import ProctoringScreenshot
from apps.proctoring.services import screenshots as screenshot_service
from apps.proctoring.tests import factories


def image_bytes(fmt="JPEG", size=(320, 240), color="red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def upload(data: bytes, name="screen.jpg", content_type="image/jpeg"):
    return SimpleUploadedFile(name, data, content_type=content_type)


class ImageDetectionTests(TestCase):
    """`_detect_image` — yagona ishonchli manba baytlarning o'zi."""

    def test_accepts_jpeg(self):
        fmt, mime, ext, (width, height) = screenshot_service._detect_image(
            image_bytes("JPEG")
        )
        self.assertEqual((fmt, mime, ext), ("JPEG", "image/jpeg", "jpg"))
        self.assertEqual((width, height), (320, 240))

    def test_accepts_png_and_webp(self):
        for fmt, mime in (("PNG", "image/png"), ("WEBP", "image/webp")):
            with self.subTest(fmt=fmt):
                self.assertEqual(
                    screenshot_service._detect_image(image_bytes(fmt))[1], mime
                )

    def test_rejects_html_disguised_as_jpeg(self):
        """
        SAQLANGAN XSS: `.jpg` nomi ostidagi HTML.

        Kengaytma ham, `Content-Type` ham client tomonidan yoziladi;
        agar ular ishonchli deb qabul qilinsa, bu fayl proktorning
        brauzerida skript sifatida bajarilardi.
        """
        payload = b"<html><script>alert(document.cookie)</script></html>"
        with self.assertRaises(ScreenshotRejected):
            screenshot_service._detect_image(payload)

    def test_rejects_svg(self):
        """
        SVG - rasm, lekin u SKRIPT saqlay oladi.

        Shuning uchun u ruxsat etilgan formatlar ro'yxatida yo'q.
        """
        payload = b'<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>'
        with self.assertRaises(ScreenshotRejected):
            screenshot_service._detect_image(payload)

    def test_rejects_unsupported_image_format(self):
        with self.assertRaises(ScreenshotRejected):
            screenshot_service._detect_image(image_bytes("BMP"))

    def test_rejects_truncated_image(self):
        """
        Kesilgan fayl `verify()` da tushadi.

        Sarlavhasi to'g'ri, ichi buzilgan fayl proktor uchun ochilmaydigan
        dalil bo'lardi.
        """
        data = image_bytes("PNG")
        with self.assertRaises(ScreenshotRejected):
            screenshot_service._detect_image(data[: len(data) // 2])

    @override_settings(
        SCREENSHOT_STORAGE={
            **__import__("django.conf").conf.settings.SCREENSHOT_STORAGE,
            "MAX_PIXELS": 1000,
        }
    )
    def test_rejects_decompression_bomb_before_decoding(self):
        """
        Dekompressiya bombasi: kichik fayl, ulkan o'lcham.

        O'lcham SARLAVHADAN o'qiladi va tekshiruv piksellarni ochishdan
        OLDIN bajariladi — aks holda Pillow RAM'ni yeb qo'yadi.
        """
        with self.assertRaises(ScreenshotRejected):
            screenshot_service._detect_image(image_bytes("PNG", size=(200, 200)))


class ReadUploadTests(TestCase):
    def test_rejects_declared_size_over_limit(self):
        big = upload(b"x" * 10)
        big.size = 999_999_999
        with self.assertRaises(ScreenshotTooLarge):
            screenshot_service._read_upload(big)

    @override_settings(
        SCREENSHOT_STORAGE={
            **__import__("django.conf").conf.settings.SCREENSHOT_STORAGE,
            "MAX_BYTES": 100,
        }
    )
    def test_rejects_actual_size_over_limit(self):
        """
        `upload.size` ga ISHONMAYMIZ.

        U `Content-Length` dan keladi va uni client istalgancha yozadi:
        "size=1KB" deb aytib 1 GB yuborish mumkin bo'lardi. Chegara
        o'qish PAYTIDA ham tekshiriladi.
        """
        payload = b"x" * 5_000
        big = upload(payload)
        big.size = 10  # yolg'on
        with self.assertRaises(ScreenshotTooLarge):
            screenshot_service._read_upload(big)

    def test_rejects_empty_file(self):
        with self.assertRaises(ScreenshotRejected):
            screenshot_service._read_upload(upload(b""))


class RelativePathTests(TestCase):
    def test_path_layout(self):
        moment = datetime(2026, 9, 7, 10, 15, 0, tzinfo=dt_timezone.utc)
        path = screenshot_service._build_relative_path(
            exam_id=7, session_id=42, captured_at=moment, seq=3, extension="jpg"
        )
        self.assertEqual(path, "7/42/20260907T101500_3.jpg")

    def test_path_uses_utc(self):
        """
        Vaqt UTC'da yoziladi.

        Mahalliy vaqt server mintaqasi o'zgarganda bir xil sessiyada
        ikki xil nom berardi; `:` esa Windows'da fayl nomida umuman
        ruxsat etilmaydi.
        """
        moment = datetime(2026, 9, 7, 23, 30, 0, tzinfo=dt_timezone.utc)
        path = screenshot_service._build_relative_path(
            exam_id=1, session_id=1, captured_at=moment, seq=0, extension="png"
        )
        self.assertIn("20260907T233000", path)
        self.assertNotIn(":", path)


class ScreenshotStoreTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.session = factories.make_session()
        self.storage = get_screenshot_storage()

    def test_stores_file_and_row(self):
        screenshot = screenshot_service.screenshot_store(
            session=self.session,
            upload=upload(image_bytes()),
            captured_at=timezone.now(),
        )
        self.assertTrue(self.storage.exists(screenshot.file_path))
        self.assertEqual(screenshot.mime_type, "image/jpeg")
        self.assertEqual(len(screenshot.content_hash), 64)

    def test_path_is_relative_never_absolute(self):
        """
        DB'da FAQAT nisbiy yo'l.

        Absolyut yo'l saqlansa: storage root ko'chganda barcha qatorlar
        bir vaqtda yaroqsiz bo'ladi va u API javobida server katalog
        strukturasini oshkor qiladi.
        """
        screenshot = screenshot_service.screenshot_store(
            session=self.session,
            upload=upload(image_bytes()),
            captured_at=timezone.now(),
        )
        self.assertFalse(screenshot.file_path.startswith("/"))
        self.assertNotIn(":", screenshot.file_path)
        self.assertTrue(screenshot.file_path.startswith(f"{self.session.exam_id}/"))

    def test_same_second_uploads_get_distinct_names(self):
        """Bir soniyada bir necha kadr — `seq` ularni ajratadi."""
        moment = timezone.now()
        paths = {
            screenshot_service.screenshot_store(
                session=self.session, upload=upload(image_bytes()), captured_at=moment
            ).file_path
            for _ in range(3)
        }
        self.assertEqual(len(paths), 3)

    def test_file_is_removed_when_row_cannot_be_written(self):
        """
        Yozish tartibi: avval fayl, keyin qator.

        Qator yozilmasa fayl DARHOL o'chiriladi — aks holda diskda
        hech kim bilmaydigan yetim fayl qoladi va uni topish uchun
        butun daraxtni DB bilan solishtirish kerak bo'lardi.
        """
        with mock.patch.object(
            ProctoringScreenshot.objects, "create", side_effect=DatabaseError("boom")
        ):
            with self.assertRaises(DatabaseError):
                screenshot_service.screenshot_store(
                    session=self.session,
                    upload=upload(image_bytes()),
                    captured_at=timezone.now(),
                )

        self.assertEqual(ProctoringScreenshot.objects.count(), 0)
        # Diskda ham hech nima qolmasligi kerak.
        root = self.storage.root / str(self.session.exam_id) / str(self.session.pk)
        self.assertFalse(root.exists() and any(root.iterdir()))

    def test_storage_failure_becomes_domain_error(self):
        with mock.patch.object(
            type(self.storage), "save", side_effect=OSError("disk to'la")
        ):
            with self.assertRaises(ScreenshotStoreFailed):
                screenshot_service.screenshot_store(
                    session=self.session,
                    upload=upload(image_bytes()),
                    captured_at=timezone.now(),
                )

    def test_future_capture_time_is_clamped(self):
        """
        Soati adashgan mashina 2030-yildagi fayl nomini yaratmasligi kerak:
        retention (`captured_at < cutoff`) unga hech qachon yetmasdi.
        """
        future = timezone.now() + timezone.timedelta(days=365)
        screenshot = screenshot_service.screenshot_store(
            session=self.session, upload=upload(image_bytes()), captured_at=future
        )
        self.assertLess(screenshot.captured_at, timezone.now() + timezone.timedelta(minutes=1))


class ScreenshotDeleteTests(RedisStateMixin, TestCase):
    def test_deletes_file_before_row(self):
        session = factories.make_session()
        screenshot = screenshot_service.screenshot_store(
            session=session, upload=upload(image_bytes()), captured_at=timezone.now()
        )
        path = screenshot.file_path

        self.assertTrue(screenshot_service.screenshot_delete(screenshot))
        self.assertFalse(get_screenshot_storage().exists(path))
        self.assertEqual(ProctoringScreenshot.objects.count(), 0)

    def test_missing_file_still_removes_row(self):
        """
        Fayli yo'q qator ham o'chirilishi kerak.

        Aks holda retention shu qatorda abadiy tiqilib qolardi.
        """
        session = factories.make_session()
        screenshot = screenshot_service.screenshot_store(
            session=session, upload=upload(image_bytes()), captured_at=timezone.now()
        )
        get_screenshot_storage().delete(screenshot.file_path)

        self.assertFalse(screenshot_service.screenshot_delete(screenshot))
        self.assertEqual(ProctoringScreenshot.objects.count(), 0)
