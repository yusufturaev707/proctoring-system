"""
Administrator huquqi bilan qayta ochish (`core/elevation.py`).

Qo'riqlanadigan narsalar:

  1. qayta ochish FAQAT cheklangan tokenda (administrator hisobi, UAC
     bo'lingan token) - oddiy hisobda va vazifa ochgan nusxada tsikl yo'q;
  2. vazifa boshqa `.exe` ni ochsa (build mashinasidagi `dist\\`) - yo'q;
  3. yangi nusxa ochilmasa dastur oddiy huquqda DAVOM ETADI;
  4. mutex holatini tekshirish uni YARATMAYDI.
"""

import sys
import unittest
import uuid
from unittest import mock

from core import elevation
from core import single_instance

EXE = r"C:\Program Files\ProctoringClient\ProctoringClient.exe"


def decide(**overrides):
    params = dict(
        frozen=True, argv=[EXE], elevation_type=elevation.ELEVATION_LIMITED,
        task_command=EXE, exe=EXE,
    )
    params.update(overrides)
    return elevation.should_relaunch(**params)


class ShouldRelaunchTests(unittest.TestCase):
    def test_limited_admin_token_relaunches(self):
        self.assertTrue(decide())
        self.assertTrue(decide(task_command='"{}"'.format(EXE)))
        self.assertTrue(decide(task_command=EXE.lower()))

    def test_no_loop_for_full_or_standard_token(self):
        self.assertFalse(decide(elevation_type=elevation.ELEVATION_FULL))
        self.assertFalse(decide(elevation_type=elevation.ELEVATION_DEFAULT))
        self.assertFalse(decide(elevation_type=0))

    def test_other_conditions(self):
        self.assertFalse(decide(frozen=False))
        self.assertFalse(decide(argv=[EXE, "--restart-count", "1"]))
        self.assertFalse(decide(task_command=""))
        self.assertFalse(decide(task_command=r"C:\build\dist\ProctoringClient\ProctoringClient.exe"))

    def test_task_command_parsed_from_xml(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><Task><Actions><Exec>' \
              "<Command>{}</Command></Exec></Actions></Task>".format(EXE)
        for data in (xml.encode("utf-16"), xml.encode("ascii")):
            with self.subTest(utf16=data[:2] == b"\xff\xfe"), \
                    mock.patch.object(elevation, "_schtasks", return_value=mock.Mock(returncode=0, stdout=data)):
                self.assertEqual(elevation.task_command(), EXE)
        with mock.patch.object(elevation, "_schtasks", return_value=mock.Mock(returncode=1, stdout=b"")):
            self.assertEqual(elevation.task_command(), "")


class RelaunchFlowTests(unittest.TestCase):
    def setUp(self):
        for target, value in (
            ("elevation_type", elevation.ELEVATION_LIMITED),
            ("task_command", EXE),
        ):
            patcher = mock.patch.object(elevation, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (("frozen", True), ("argv", [EXE]), ("executable", EXE)):
            patcher = mock.patch.object(sys, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.release = mock.Mock()
        self.reacquire = mock.Mock(return_value=True)

    def run_flow(self, held, run_code=0):
        result = mock.Mock(
            returncode=run_code,
            stdout=b"",
            stderr=b"ERROR: Access is denied.\r\n" if run_code else b"",
        )
        with mock.patch.object(elevation, "_schtasks", return_value=result) as run, \
                mock.patch.object(elevation, "WAIT_SECONDS", 0.3), \
                mock.patch.object(elevation, "_POLL_SECONDS", 0.05):
            result = elevation.relaunch_via_task(self.release, mock.Mock(return_value=held), self.reacquire)
        return result, run

    def test_new_instance_took_over(self):
        result, run = self.run_flow(held=True)
        self.assertTrue(result)
        self.release.assert_called_once()
        self.reacquire.assert_not_called()
        run.assert_called_once_with("/Run", "/TN", elevation.TASK_NAME)

    def test_timeout_continues_unelevated(self):
        result, _run = self.run_flow(held=False)
        self.assertFalse(result)
        self.reacquire.assert_called_once()

    def test_task_run_failure_continues(self):
        with self.assertLogs("core.elevation", "WARNING") as logs:
            result, _run = self.run_flow(held=False, run_code=1)
        self.assertFalse(result)
        self.reacquire.assert_called_once()
        # Sabab log'da - "kod 1" ning o'zi diagnostika uchun yetmaydi.
        self.assertIn("Access is denied", logs.output[0])

    def test_late_instance_wins_mutex(self):
        self.reacquire.return_value = False
        result, _run = self.run_flow(held=False)
        self.assertTrue(result)

    def test_not_needed_touches_nothing(self):
        with mock.patch.object(elevation, "elevation_type", return_value=elevation.ELEVATION_FULL), \
                mock.patch.object(elevation, "_schtasks") as run:
            self.assertFalse(elevation.relaunch_via_task(self.release, mock.Mock(), self.reacquire))
        run.assert_not_called()
        self.release.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows mutex")
class MutexProbeTests(unittest.TestCase):
    def test_is_held_does_not_create(self):
        name = "Local\\ProctoringClient.Test." + uuid.uuid4().hex
        self.assertFalse(single_instance.is_held(name))
        # Tekshiruv mutex'ni yaratmagan - birinchi `acquire` egallay oladi.
        saved = single_instance._handle
        single_instance._handle = None
        try:
            self.assertTrue(single_instance.acquire(name))
            self.assertTrue(single_instance.is_held(name))
            single_instance.release()
            self.assertIsNone(single_instance._handle)
            self.assertFalse(single_instance.is_held(name))
        finally:
            single_instance._handle = saved

    def test_current_token_type_is_known(self):
        self.assertIn(
            elevation.elevation_type(),
            (elevation.ELEVATION_DEFAULT, elevation.ELEVATION_FULL, elevation.ELEVATION_LIMITED),
        )
