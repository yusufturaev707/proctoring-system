"""
`proctoring/stop/` - faqat sessiya TIRIK qolganda (`ExamWebViewPage._notify_proctoring_stop`).

Yakun, chetlashtirish va muddat tugashi kuzatuvni serverda o'zi yopadi
(`session._complete_proctoring`) va tokenni bekor qiladi: ulardan
keyingi chaqiruv har safar 404 olardi.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from ui.pages.exam_webview_page import ExamWebViewPage


def page(*, closed=False, pending=None, token="tok"):
    return SimpleNamespace(
        _session_closed=closed,
        _pending_access=pending,
        _state=SimpleNamespace(session=SimpleNamespace(token=token) if token else None),
        _repo=SimpleNamespace(proctoring_stop=mock.Mock()),
        _workers=mock.Mock(),
    )


class NotifyProctoringStopTests(unittest.TestCase):
    def notify(self, stub):
        with mock.patch("ui.pages.exam_webview_page.ApiWorker") as worker:
            ExamWebViewPage._notify_proctoring_stop(stub)
        return worker

    def test_closed_session_sends_nothing(self):
        stub = page(closed=True)
        worker = self.notify(stub)
        worker.assert_not_called()
        stub._workers.run.assert_not_called()

    def test_live_session_is_notified(self):
        stub = page()
        worker = self.notify(stub)
        worker.assert_called_once()
        stub._workers.run.assert_called_once()

    def test_not_started_or_tokenless_sends_nothing(self):
        for stub in (page(pending={"x": 1}), page(token="")):
            with self.subTest():
                self.notify(stub).assert_not_called()


if __name__ == "__main__":
    unittest.main()
