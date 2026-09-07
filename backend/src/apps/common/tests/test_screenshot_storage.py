"""
Skrinshot storage qatlami.

Diqqat markazida — **yo'l tekshiruvi**. Yo'l DB'dan keladi va shuning
uchun "ishonchli" ko'rinadi, lekin u `serve()` orqali nginx'ning
`internal` location'iga uzatiladi: bitta `../../..` bilan storage
root'idan tashqaridagi istalgan fayl proktorning brauzerida ochiladi.
"""

import os
import shutil
import tempfile

from django.core.exceptions import SuspiciousFileOperation
from django.test import SimpleTestCase, override_settings

from apps.common.screenshot_storage import (
    FilesystemScreenshotStorage,
    ScreenshotAlreadyExists,
    safe_relative_path,
)

#: Eng kichik haqiqiy JPEG emas — storage baytlarni tekshirmaydi
#: (bu `services/screenshots.py` ning ishi), shuning uchun oddiy bayt.
PAYLOAD = b"\xff\xd8\xff\xdb" + b"0" * 64


class SafeRelativePathTests(SimpleTestCase):
    def test_accepts_normal_path(self):
        self.assertEqual(
            str(safe_relative_path("12/345/20260907T101500_1.jpg")),
            "12/345/20260907T101500_1.jpg",
        )

    def test_normalizes_backslashes(self):
        """Windows'da yozilgan yo'l Linux'da o'qilishi mumkin."""
        self.assertEqual(str(safe_relative_path(r"12\345\a.jpg")), "12/345/a.jpg")

    def test_rejects_parent_traversal(self):
        for value in ("../etc/passwd", "12/../../secret", "a/b/../../../c"):
            with self.subTest(value=value):
                with self.assertRaises(SuspiciousFileOperation):
                    safe_relative_path(value)

    def test_rejects_absolute_path(self):
        for value in ("/etc/passwd", "//server/share/x"):
            with self.subTest(value=value):
                with self.assertRaises(SuspiciousFileOperation):
                    safe_relative_path(value)

    def test_rejects_windows_drive(self):
        """
        `C:/x` POSIX qoidasi bo'yicha absolyut HISOBLANMAYDI.

        Ya'ni oddiy `is_absolute()` tekshiruvi uni o'tkazib yuboradi,
        `Path` esa uni disk ildizi deb tushunadi.
        """
        with self.assertRaises(SuspiciousFileOperation):
            safe_relative_path("C:/Windows/win.ini")

    def test_rejects_nul_byte(self):
        with self.assertRaises(SuspiciousFileOperation):
            safe_relative_path("a/b\x00.jpg")

    def test_rejects_empty(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                with self.assertRaises(SuspiciousFileOperation):
                    safe_relative_path(value)


class FilesystemStorageTests(SimpleTestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="shot-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.storage = FilesystemScreenshotStorage(
            root=self.root, internal_location="/protected", serve_directly=False
        )

    # --- save ------------------------------------------------------
    def test_save_creates_file_with_content(self):
        written = self.storage.save("7/42/frame_1.jpg", PAYLOAD)
        self.assertEqual(written, len(PAYLOAD))
        self.assertTrue(self.storage.exists("7/42/frame_1.jpg"))
        with open(os.path.join(self.root, "7", "42", "frame_1.jpg"), "rb") as handle:
            self.assertEqual(handle.read(), PAYLOAD)

    def test_save_refuses_to_overwrite(self):
        """
        Ustidan yozish MUMKIN EMAS.

        Har bir fayl bitta DB qatoriga tegishli; uni bosib o'tish
        boshqa sessiyaning dalilini yo'q qiladi. Chaqiruvchi bu
        istisnoni ko'rib `seq` ni oshiradi.
        """
        self.storage.save("7/42/frame_1.jpg", PAYLOAD)
        with self.assertRaises(ScreenshotAlreadyExists):
            self.storage.save("7/42/frame_1.jpg", b"boshqa")

    def test_save_with_overwrite_flag(self):
        self.storage.save("7/42/frame_1.jpg", PAYLOAD)
        self.storage.save("7/42/frame_1.jpg", b"yangi", overwrite=True)
        with open(os.path.join(self.root, "7", "42", "frame_1.jpg"), "rb") as handle:
            self.assertEqual(handle.read(), b"yangi")

    def test_save_leaves_no_temporary_files(self):
        """Atomik yozish `.tmp` qoldiqlarini qoldirmasligi kerak."""
        self.storage.save("7/42/frame_1.jpg", PAYLOAD)
        names = os.listdir(os.path.join(self.root, "7", "42"))
        self.assertEqual(names, ["frame_1.jpg"])

    def test_save_rejects_traversal(self):
        with self.assertRaises(SuspiciousFileOperation):
            self.storage.save("../escape.jpg", PAYLOAD)

    # --- delete / exists -------------------------------------------
    def test_delete_returns_true_then_false(self):
        self.storage.save("7/42/a.jpg", PAYLOAD)
        self.assertTrue(self.storage.delete("7/42/a.jpg"))
        self.assertFalse(self.storage.delete("7/42/a.jpg"))

    def test_delete_of_unsafe_path_returns_false_and_deletes_nothing(self):
        """
        Buzilgan yo'lli qator o'chirilishi kerak, lekin uning nomidan
        fayl tizimida hech narsa o'chirilmaydi.
        """
        outside = os.path.join(self.root, "..", "boshqa.txt")
        with open(outside, "wb") as handle:
            handle.write(b"tegilmasin")
        self.addCleanup(os.unlink, outside)

        self.assertFalse(self.storage.delete("../boshqa.txt"))
        self.assertTrue(os.path.exists(outside))

    def test_exists_is_false_for_unsafe_path(self):
        self.assertFalse(self.storage.exists("../../etc/passwd"))

    # --- serve -----------------------------------------------------
    def test_serve_returns_accel_redirect_without_body(self):
        self.storage.save("7/42/a.jpg", PAYLOAD)
        response = self.storage.serve("7/42/a.jpg", content_type="image/jpeg")

        self.assertEqual(response["X-Accel-Redirect"], "/protected/7/42/a.jpg")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        # Baytlar Python'dan O'TMAYDI — ularni nginx o'qiydi.
        self.assertEqual(response.content, b"")

    def test_serve_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.storage.serve("7/42/yoq.jpg", content_type="image/jpeg")

    def test_serve_directly_streams_bytes(self):
        """Dev rejimi: nginx yo'q, faylni Django o'zi beradi."""
        storage = FilesystemScreenshotStorage(root=self.root, serve_directly=True)
        storage.save("7/42/a.jpg", PAYLOAD)
        response = storage.serve("7/42/a.jpg", content_type="image/jpeg")
        self.assertEqual(b"".join(response.streaming_content), PAYLOAD)

    def test_internal_url_quotes_special_characters(self):
        url = self.storage.internal_url("7/42/a b.jpg")
        self.assertEqual(url, "/protected/7/42/a%20b.jpg")

    # --- prune -----------------------------------------------------
    def test_prune_removes_empty_dirs_only(self):
        self.storage.save("7/42/a.jpg", PAYLOAD)
        self.storage.save("7/43/b.jpg", PAYLOAD)
        self.storage.delete("7/43/b.jpg")

        removed = self.storage.prune_empty_dirs()

        self.assertGreaterEqual(removed, 1)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "7", "43")))
        # Ichida fayli bor katalog TEGILMAYDI.
        self.assertTrue(os.path.isfile(os.path.join(self.root, "7", "42", "a.jpg")))

    def test_prune_keeps_root(self):
        self.storage.prune_empty_dirs()
        self.assertTrue(os.path.isdir(self.root))


class StorageFactoryTests(SimpleTestCase):
    """
    Fabrika sozlamadagi backend'ni qaytaradi va NUSXANI KESHLAYDI.

    Kesh muhim: `FilesystemScreenshotStorage.__init__` `Path.resolve()`
    chaqiradi va u fayl tizimiga murojaat qiladi — har skrinshotda
    yangi nusxa yaratish ingest yo'liga keraksiz syscall qo'shardi.
    """

    def test_returns_configured_backend_and_caches_it(self):
        from apps.common.screenshot_storage import (
            get_screenshot_storage,
            reset_screenshot_storage,
        )

        reset_screenshot_storage()
        self.addCleanup(reset_screenshot_storage)

        storage = get_screenshot_storage()
        self.assertIsInstance(storage, FilesystemScreenshotStorage)
        self.assertIs(storage, get_screenshot_storage())
