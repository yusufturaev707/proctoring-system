"""
IP kamera holati (RTSP `DESCRIBE`) va paneldagi jonli ko'rish.

Haqiqiy kamera o'rniga TEST ICHIDAGI RTSP SERVER ishlatiladi: u Digest
autentifikatsiyani ham, 404 ni ham xuddi kamera kabi qaytaradi. Shu
tufayli "online / xatolik / offline" farqi haqiqiy protokol ustida
tekshiriladi, soxta obyekt ustida emas.
"""

import hashlib
import os
import re
import socket
import tempfile
import threading
import time
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.devices import camera_live, camera_probe, services
from apps.devices.models import Camera
from apps.proctoring.models import AuditLog
from apps.proctoring.tests import factories

_REALM = "IP Camera"
_NONCE = "abc123"


class FakeRtspServer:
    """Bitta ulanishga bitta yoki ikkita `DESCRIBE` javobini beradi."""

    def __init__(self, *, login="viewer", password="secret", path="/Streaming/Channels/101"):
        self.login, self.password, self.path = login, password, path
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self._stop = True
        self.sock.close()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    while True:
                        data = b""
                        while b"\r\n\r\n" not in data:
                            chunk = conn.recv(4096)
                            if not chunk:
                                raise ConnectionError
                            data += chunk
                        conn.sendall(self._reply(data.decode("latin-1")).encode("latin-1"))
                except (ConnectionError, OSError):
                    continue

    def _reply(self, request: str) -> str:
        first = request.split("\r\n", 1)[0]
        cseq = re.search(r"CSeq:\s*(\d+)", request).group(1)
        url = first.split(" ")[1]
        if not url.endswith(self.path):
            return "RTSP/1.0 404 Not Found\r\nCSeq: {}\r\n\r\n".format(cseq)
        auth = re.search(r"Authorization:\s*(.+)", request)
        if not auth:
            return (
                'RTSP/1.0 401 Unauthorized\r\nCSeq: {}\r\n'
                'WWW-Authenticate: Basic realm="{}"\r\n'
                'WWW-Authenticate: Digest realm="{}", nonce="{}"\r\n\r\n'
            ).format(cseq, _REALM, _REALM, _NONCE)
        params = dict(re.findall(r'(\w+)="([^"]*)"', auth.group(1)))
        ha1 = hashlib.md5("{}:{}:{}".format(self.login, _REALM, self.password).encode()).hexdigest()
        ha2 = hashlib.md5("DESCRIBE:{}".format(params.get("uri", "")).encode()).hexdigest()
        expected = hashlib.md5("{}:{}:{}".format(ha1, _NONCE, ha2).encode()).hexdigest()
        if params.get("username") == self.login and params.get("response") == expected:
            return "RTSP/1.0 200 OK\r\nCSeq: {}\r\nContent-Type: application/sdp\r\n\r\n".format(cseq)
        return (
            'RTSP/1.0 401 Unauthorized\r\nCSeq: {}\r\n'
            'WWW-Authenticate: Digest realm="{}", nonce="{}"\r\n\r\n'
        ).format(cseq, _REALM, _NONCE)


class CameraProbeTests(TestCase):
    def setUp(self):
        self.server = FakeRtspServer()
        self.addCleanup(self.server.close)

    def _probe(self, **kwargs):
        params = dict(host="127.0.0.1", port=self.server.port, path="/Streaming/Channels/101",
                      login="viewer", password="secret", timeout=2)
        params.update(kwargs)
        return camera_probe.probe(**params)

    def test_digest_auth_success_is_online(self):
        """Digest afzal ko'riladi (kamera Basic ni ham taklif qiladi) va o'tadi."""
        result = self._probe()
        self.assertEqual(result.status, camera_probe.ONLINE, result.message)

    def test_wrong_password_is_error_with_reason(self):
        result = self._probe(password="wrong")
        self.assertEqual(result.status, camera_probe.ERROR)
        self.assertIn("parol", result.message)

    def test_wrong_path_is_error_with_reason(self):
        result = self._probe(path="/wrong")
        self.assertEqual(result.status, camera_probe.ERROR)
        self.assertIn("topilmadi", result.message)

    def test_closed_port_is_offline(self):
        with socket.socket() as probe_sock:
            probe_sock.bind(("127.0.0.1", 0))
            free_port = probe_sock.getsockname()[1]
        result = self._probe(port=free_port)
        self.assertEqual(result.status, camera_probe.OFFLINE)


class CameraStatusServiceTests(TestCase):
    def setUp(self):
        self.server = FakeRtspServer()
        self.addCleanup(self.server.close)
        self.camera = factories.make_camera(
            ip_address="127.0.0.1", port=self.server.port, login="viewer",
            rtsp_path="/Streaming/Channels/101",
        )
        services.set_camera_password(self.camera, "secret")
        self.camera.save()

    def test_check_writes_status_and_timestamps(self):
        services.check_camera(self.camera)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.status, Camera.Status.ONLINE)
        self.assertIsNotNone(self.camera.last_seen_at)
        self.assertIsNotNone(self.camera.last_checked_at)

    def test_error_keeps_last_seen_and_explains(self):
        """
        Xatolikda `last_seen_at` O'ZGARMAYDI - u "oxirgi marta ishlagan
        payt"; `status_message` esa nimani tuzatishni aytadi.
        """
        services.check_camera(self.camera)
        self.camera.refresh_from_db()
        seen = self.camera.last_seen_at

        services.set_camera_password(self.camera, "changed")
        self.camera.save()
        services.check_camera(self.camera)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.status, Camera.Status.ERROR)
        self.assertEqual(self.camera.last_seen_at, seen)
        self.assertIn("parol", self.camera.status_message)

    @override_settings(CAMERA_PROBE_ENABLED=False)
    def test_periodic_task_can_be_disabled(self):
        from apps.devices.tasks import probe_cameras

        self.assertEqual(probe_cameras(), {"skipped": True})


class CameraApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.server = FakeRtspServer()
        self.addCleanup(self.server.close)
        self.camera = factories.make_camera(
            ip_address="127.0.0.1", port=self.server.port, login="viewer",
            rtsp_path="/Streaming/Channels/101",
        )
        services.set_camera_password(self.camera, "secret")
        self.camera.save()
        self.manager = factories.make_user(permissions=["devices.manage", "devices.view"])
        self.viewer = factories.make_user(permissions=["devices.view"])

    def test_check_action_returns_fresh_status(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(reverse("camera-check", args=[self.camera.pk]))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["status"], "online")
        self.assertIn("last_checked_at", data)

    def test_view_only_user_cannot_see_live_image(self):
        """Ro'yxatni ko'rish huquqi imtihon xonasining jonli tasvirini OCHMAYDI."""
        self.client.force_authenticate(self.viewer)
        response = self.client.get(reverse("camera-snapshot", args=[self.camera.pk]))
        self.assertEqual(response.status_code, 403)

    def test_snapshot_returns_jpeg_and_is_audited_once(self):
        video = _make_video()
        self.addCleanup(_remove_when_released, video)
        self.client.force_authenticate(self.manager)
        with mock.patch.object(services, "build_rtsp_url", return_value=video), \
                mock.patch("apps.common.redis_client.get_redis", side_effect=RuntimeError):
            first = self.client.get(reverse("camera-snapshot", args=[self.camera.pk]))
        self.assertEqual(first.status_code, 200, first.content[:300])
        self.assertEqual(first["Content-Type"], "image/jpeg")
        self.assertTrue(first.content.startswith(b"\xff\xd8"))
        self.assertIn("X-Frame-Taken-At", first)
        self.assertTrue(
            AuditLog.objects.filter(action="camera_live_view", object_id=str(self.camera.pk)).exists()
        )

    def test_live_stream_is_multipart_with_frame_timing(self):
        """
        Jonli oqim - bitta javobda ketma-ket JPEG qismlari (MJPEG).

        Har qismda uzunlik (panel chegarani qidirmay kesadi) va ikki
        vaqt: olingan va yuborilgan - panel server ichidagi kechikishni
        shulardan ko'rsatadi.
        """
        video = _make_video()
        self.addCleanup(_remove_when_released, video)
        self.client.force_authenticate(self.manager)
        with mock.patch.object(services, "build_rtsp_url", return_value=video):
            response = self.client.get(reverse("camera-live", args=[self.camera.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("multipart/x-mixed-replace"))
            self.assertEqual(response["X-Accel-Buffering"], "no")
            # Oqim OXIRIGACHA o'qiladi (video 2 s, o'quvchi o'zi tugaydi):
            # `response.close()` ni qo'lda chaqirish `request_finished`
            # orqali test tranzaksiyasining DB ulanishini yopib qo'yardi.
            chunks = list(response.streaming_content)
        self.assertGreater(len(chunks), 1)
        first = chunks[0]
        head, _, body = first.partition(b"\r\n\r\n")
        text = head.decode("ascii")
        self.assertIn("--cameraframe", text)
        length = int(re.search(r"Content-Length: (\d+)", text).group(1))
        self.assertTrue(body[:length].startswith(b"\xff\xd8"))
        taken = float(re.search(r"X-Frame-Taken-At: ([\d.]+)", text).group(1))
        sent = float(re.search(r"X-Frame-Sent-At: ([\d.]+)", text).group(1))
        self.assertGreaterEqual(sent, taken)

    def test_live_stream_respects_concurrency_limit(self):
        """Band bo'lsa 503 - oddiy API thread'lari ko'ruvchilarga qolib ketmasin."""
        from apps.devices.api.v1 import views as device_views

        self.client.force_authenticate(self.manager)
        with mock.patch.object(device_views, "_LIVE_SLOTS") as slots:
            slots.acquire.return_value = False
            response = self.client.get(reverse("camera-live", args=[self.camera.pk]))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "camera_viewer_busy")

    def test_view_only_user_cannot_open_live_stream(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(reverse("camera-live", args=[self.camera.pk]))
        self.assertEqual(response.status_code, 403)

    def test_unreachable_stream_gives_readable_error(self):
        self.client.force_authenticate(self.manager)
        with mock.patch.object(services, "build_rtsp_url", return_value="rtsp://127.0.0.1:1/none"), \
                mock.patch.object(camera_live, "_OPEN_TIMEOUT_MS", 1000), \
                mock.patch.object(camera_live, "_FIRST_FRAME_TIMEOUT", 4.0):
            response = self.client.get(reverse("camera-snapshot", args=[self.camera.pk]))
        self.assertEqual(response.status_code, 502)
        self.assertIn("Oqim", response.content.decode())


def _make_video() -> str:
    """2 soniyalik sintetik video - OpenCV/FFmpeg uni RTSP kabi o'qiydi."""
    import cv2
    import numpy as np

    handle, path = tempfile.mkstemp(suffix=".mp4")
    os.close(handle)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for index in range(20):
        frame = np.full((240, 320, 3), index * 10, np.uint8)
        writer.write(frame)
    writer.release()
    return path


def _remove_when_released(path: str) -> None:
    """
    O'quvchi thread'i faylni yopgach o'chiradi.

    Windows ochiq faylni o'chirishga ruxsat bermaydi, o'quvchi esa
    video tugagach bir necha yuz ms da o'zi yopiladi.
    """
    deadline = time.monotonic() + 10
    while camera_live.active_readers() and time.monotonic() < deadline:
        time.sleep(0.1)
    try:
        os.remove(path)
    except OSError:
        pass
