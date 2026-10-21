"""
Yakun zanjiri: skrinshot navbati -> hodisalar -> yozuv manzili ->
`session/finish/` (bitta fon chaqiruvi).

Ilgari oxirgi hodisalar buferi `stop()` da, ya'ni yakun javobidan KEYIN
yuborilardi - token bekor, so'rov `session_not_found`, oxirgi soniyalar
va ochiq hodisalarning yopilishi yo'qolardi. Qo'riqlanadigan narsalar:

  1. navbat yakundan OLDIN olinadi, manbalar (AI, yuz epizodlari) undan oldin yopiladi;
  2. tartib: skrinshot navbati, hodisalar, yozuv, yakun; birortasi
     yakunni to'smaydi («faqat serverda» rejimida oxirgi javobning
     kadri faqat RAM'da - token bekor bo'lishidan oldin ketishi shart);
  3. chiqishdagi byudjet: sekin yordamchi qadam YAKUNNI kesmaydi;
  4. platformaning yakun buyrug'i tugma bilan bir xil yo'ldan ketadi va
     ochiq dialog ikkinchi yakun yubormaydi.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from PyQt6.QtWidgets import QApplication

from core.errors import ClientError
from services.face_presence import FaceEpisodes
from services.monitoring import SessionMonitor
from ui.pages import exam_webview_page as page_module
from ui.pages.exam_webview_page import ExamWebViewPage


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Repo:
    """Chaqiruvlar tartibini va berilgan timeout'larni yozib boradi."""

    def __init__(self, clock=None, durations=None, fail=None):
        self.calls = []
        self.clock = clock
        self.durations = durations or {}
        self.fail = fail or {}

    def _call(self, name, timeout, size=0):
        self.calls.append((name, timeout, size))
        if self.clock is not None:
            self.clock.now += self.durations.get(name, 0.0)
        error = self.fail.get(name)
        if error is not None:
            raise error

    def send_events(self, batch, *, timeout=None):
        self._call("events", timeout, len(batch))

    def register_recording(self, *, timeout=None, **_fields):
        self._call("recording", timeout)

    def finish_session(self, *, reason="", completed=False, timeout=None):
        self._call("finish", timeout)
        return {"ok": True}


class Shots:
    """`ScreenshotService.wait_idle` o'rni - chaqiruv `Repo` jurnaliga tushadi."""

    def __init__(self, repo, fail=None):
        self.repo = repo
        self.fail = fail

    def wait_idle(self, timeout):
        if self.fail is not None:
            raise self.fail
        self.repo._call("shots", timeout)
        return True


def stub(repo, shots=None):
    page = SimpleNamespace(_repo=repo, _screenshots=shots or Shots(repo))
    page._send_final_events = lambda events, side: ExamWebViewPage._send_final_events(page, events, side)
    page._log_lost_events = ExamWebViewPage._log_lost_events
    return page


def run_chain(repo, *, events, fields=None, timeout=None, shots=None):
    page = stub(repo, shots)
    return ExamWebViewPage._finish_with_recording(
        page, fields, "test", timeout, False, events
    )


def names(repo, *, skip=("shots",)):
    return [c[0] for c in repo.calls if c[0] not in skip]


EVENTS = [{"type": "window_blur", "client_event_id": str(i)} for i in range(3)]


class FinishChainTests(unittest.TestCase):
    def test_order_shots_events_recording_finish(self):
        repo = Repo()
        result = run_chain(repo, events=EVENTS, fields={"kind": "screen"})
        self.assertEqual(names(repo, skip=()), ["shots", "events", "recording", "finish"])
        self.assertEqual(repo.calls[0][1], page_module._FINISH_SHOT_DRAIN_S)
        self.assertEqual(repo.calls[1][2], 3)
        self.assertEqual(result, {"ok": True})

    def test_screenshot_wait_error_does_not_block_finish(self):
        repo = Repo()
        shots = Shots(repo, fail=RuntimeError("buzildi"))
        with self.assertLogs(page_module.log, "ERROR"):
            result = run_chain(repo, events=EVENTS, shots=shots)
        self.assertEqual(names(repo), ["events", "finish"])
        self.assertEqual(result, {"ok": True})

    def test_exit_screenshot_wait_is_capped_and_finish_keeps_full_timeout(self):
        clock = FakeClock()
        timeout = page_module._EXIT_REQUEST_TIMEOUT_S
        # Navbat bo'shamadi: kutish o'z chegarasini to'liq yeb qo'ydi.
        repo = Repo(clock=clock, durations={"shots": page_module._EXIT_SHOT_DRAIN_S})
        with mock.patch.object(page_module.time, "monotonic", clock):
            run_chain(repo, events=EVENTS, fields={"kind": "screen"}, timeout=timeout)
        self.assertEqual(repo.calls[0], ("shots", page_module._EXIT_SHOT_DRAIN_S, 0))
        self.assertEqual(repo.calls[-1], ("finish", timeout, 0))
        self.assertLessEqual(clock.now, page_module._EXIT_BUDGET_S - timeout + 1e-9)

    def test_large_queue_sent_in_batches(self):
        repo = Repo()
        events = [{"type": "window_blur"}] * (page_module.EVENT_BATCH_MAX + 5)
        run_chain(repo, events=events)
        self.assertEqual([c[2] for c in repo.calls if c[0] == "events"],
                         [page_module.EVENT_BATCH_MAX, 5])

    def test_event_failure_does_not_block_finish(self):
        repo = Repo(fail={"events": ClientError("tarmoq", code="network")})
        with self.assertLogs(page_module.log, "WARNING") as logs:
            result = run_chain(repo, events=EVENTS, fields={"kind": "screen"})
        self.assertEqual(names(repo), ["events", "recording", "finish"])
        self.assertEqual(result, {"ok": True})
        self.assertIn("3 ta hodisa yuborilmadi", "\n".join(logs.output))
        self.assertNotIn("client_event_id", "\n".join(logs.output))  # payload log'ga tushmaydi

    def test_network_error_skips_rest_poison_skips_only_itself(self):
        events = [{"type": "window_blur"}] * (page_module.EVENT_BATCH_MAX * 2)
        repo = Repo(fail={"events": ClientError("buzuq", code="bad_request", status=400)})
        with self.assertLogs(page_module.log, "WARNING"):
            run_chain(repo, events=events)
        self.assertEqual(sum(1 for c in repo.calls if c[0] == "events"), 2)

        repo = Repo(fail={"events": ClientError("tarmoq", code="network")})
        with self.assertLogs(page_module.log, "WARNING"):
            run_chain(repo, events=events)
        self.assertEqual(sum(1 for c in repo.calls if c[0] == "events"), 1)

    def test_exit_budget_keeps_full_timeout_for_finish(self):
        clock = FakeClock()
        timeout = page_module._EXIT_REQUEST_TIMEOUT_S
        # Hodisalar so'rovi o'z timeout'ini to'liq yeb qo'ydi.
        repo = Repo(clock=clock, durations={"events": timeout, "recording": 1.0})
        with mock.patch.object(page_module.time, "monotonic", clock):
            run_chain(repo, events=EVENTS, fields={"kind": "screen"}, timeout=timeout)
        self.assertEqual(names(repo), ["events", "recording", "finish"])
        finish_timeout = repo.calls[-1][1]
        self.assertEqual(finish_timeout, timeout)
        # Yakun byudjet ichida tugaydi.
        recording_timeout = next(c[1] for c in repo.calls if c[0] == "recording")
        started_finish = timeout + recording_timeout
        self.assertLessEqual(started_finish + finish_timeout, page_module._EXIT_BUDGET_S + 1e-9)

    def test_exit_budget_skips_side_step_without_time(self):
        clock = FakeClock()
        timeout = page_module._EXIT_REQUEST_TIMEOUT_S
        repo = Repo(clock=clock, durations={"events": 4.8})
        with mock.patch.object(page_module.time, "monotonic", clock), \
                self.assertLogs(page_module.log, "WARNING"):
            run_chain(repo, events=EVENTS, fields={"kind": "screen"}, timeout=timeout)
        self.assertEqual(names(repo), ["events", "finish"])


class PlatformFinishTests(unittest.TestCase):
    """`POST /api/finished_session` -> «Yakunlash» tugmasi bilan bir xil yo'l."""

    def make_page(self, *, exam_open=True):
        calls = []
        page = SimpleNamespace(
            _exam_open=exam_open, _modal_dialog=mock.Mock(), _warning=mock.Mock(),
            finish=lambda **kwargs: calls.append(kwargs),
        )
        return page, calls

    def test_same_path_as_finish_button(self):
        page, calls = self.make_page()
        dialog, warning = page._modal_dialog, page._warning
        ExamWebViewPage._on_platform_finished(page, {"pinfl": "32705901230024"})
        # Ochiq «Yakunlash» dialogi yopiladi - u ikkinchi yakunni yuborardi.
        dialog.reject.assert_called_once()
        warning.dismiss.assert_called_once()
        # `completed=True` - joy bo'shaydi (tugma bilan bir xil).
        self.assertEqual(calls, [{"reason": "Test platformasida yakunlandi", "completed": True}])

    def test_ignored_when_exam_already_closed(self):
        page, calls = self.make_page(exam_open=False)
        ExamWebViewPage._on_platform_finished(page, {})
        self.assertEqual(calls, [])
        page._modal_dialog.reject.assert_not_called()

    def test_dialog_result_ignored_if_exam_closed_meanwhile(self):
        page = SimpleNamespace(_exam_open=True, _modal_dialog=None)
        dialog = mock.Mock()

        def run():
            self.assertIs(page._modal_dialog, dialog)
            page._exam_open = False  # dialog ochiq turganda platforma yakunladi
            return page_module.QDialog.DialogCode.Accepted

        dialog.exec.side_effect = run
        self.assertFalse(ExamWebViewPage._run_dialog(page, dialog))
        self.assertIsNone(page._modal_dialog)

        page._exam_open = True
        dialog.exec.side_effect = lambda: page_module.QDialog.DialogCode.Accepted
        self.assertTrue(ExamWebViewPage._run_dialog(page, dialog))


class CollectFinalEventsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_page(self, *, active=True):
        monitor = SessionMonitor(repo=mock.Mock())
        if active:
            # `start()` EMAS: u darhol heartbeat thread'ini ochadi va test
            # tugaganda ishlab turgan QThread yo'q qilinib jarayon qulaydi.
            monitor._active = True
            monitor._heartbeat_timer.start()
            monitor._flush_timer.start()
        # Havola test oxirigacha: aks holda monitor (taymerlarning otasi)
        # yig'ishtirilib, keyingi murojaat "C++ obyekt o'chirilgan" beradi.
        self._monitor = monitor
        order = []
        supervisor = SimpleNamespace(stop=lambda: order.append("supervisor"))
        episodes = FaceEpisodes(warn_s=2, suspicious_s=5)
        page = SimpleNamespace(
            _face_timer=mock.Mock(), _supervisor=supervisor,
            _monitor=monitor, _face_episodes=episodes,
        )
        return page, monitor, episodes, order

    def test_sources_closed_then_queue_drained(self):
        page, monitor, episodes, order = self.make_page()
        monitor.push_event("window_blur", severity=1)
        t = 0.0
        while t < 3.0:  # ochiq "yuz yo'q" epizodi (ogohlantirish chiqqan)
            for event in episodes.observe("none", t):
                monitor.push_event(event[0], severity=event[1], payload=event[2])
            t += 0.1
        events = ExamWebViewPage._collect_final_events(page)
        self.assertEqual(order, ["supervisor"])
        page._face_timer.stop.assert_called_once()
        self.assertEqual([(e["type"], e["severity"]) for e in events], [
            ("window_blur", 1), ("face_not_found", 2), ("face_not_found", 0),
        ])
        self.assertTrue(events[-1]["payload"]["closed"])
        self.assertEqual(monitor.pending_events, 0)
        self.assertFalse(monitor._flush_timer.isActive())
        self.assertFalse(monitor._heartbeat_timer.isActive())

    def test_inactive_monitor_gives_nothing(self):
        page, monitor, _episodes, order = self.make_page(active=False)
        monitor.push_event("window_blur", severity=1)  # boshqa sessiyaga tegishli
        self.assertEqual(ExamWebViewPage._collect_final_events(page), [])
        self.assertEqual(monitor.pending_events, 1)
        self.assertEqual(order, ["supervisor"])


if __name__ == "__main__":
    unittest.main()
