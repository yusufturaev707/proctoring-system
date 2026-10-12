"""
Ctrl+Q oynasi: orqaga qaytish ham, chiqish ham PAROL bilan.

Qo'riqlanadigan narsalar:

  1. «orqaga» tugmasi parolsiz yopilmaydi;
  2. har amal serverga o'z `purpose` i bilan ketadi va oyna o'sha
     amalning natijasini qaytaradi (`BACK` / `Accepted`);
  3. noto'g'ri parol oynani yopmaydi;
  4. Enter — xavfsiz amal (orqaga, bo'lsa);
  5. parol sozlanmagan viloyatda ikkala amal ham tasdiq bilan o'tadi.
"""

import unittest
from unittest import mock

from PyQt6.QtWidgets import QApplication, QDialog

from core.errors import ClientError
from ui.dialogs import exit_dialog as module
from ui.dialogs.exit_dialog import ExitDialog


class _SyncWorker:
    """`ApiWorker` o'rniga: funksiyani darhol chaqiradi (thread'siz)."""

    def __init__(self, func, *args, parent=None, **kwargs):
        self._call = lambda: func(*args, **kwargs)
        self._ok, self._fail = [], []
        self.succeeded = mock.Mock(connect=self._ok.append)
        self.failed = mock.Mock(connect=self._fail.append)

    def run(self):
        try:
            result = self._call()
        except ClientError as exc:
            for slot in self._fail:
                slot(exc.message, exc.code)
        else:
            for slot in self._ok:
                slot(result)


class _Holder:
    def run(self, worker):
        worker.run()

    def wait_all(self, *_args):
        pass


class ExitDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = mock.patch.object(module, "ApiWorker", _SyncWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = mock.Mock()
        self.repo.verify_exit.return_value = {"method": "region"}

    def _dialog(self, back=True):
        dialog = ExitDialog(None, repo=self.repo, back_label="Orqaga" if back else "")
        dialog._workers = _Holder()
        self.results = []
        dialog.finished.connect(self.results.append)
        return dialog

    def test_back_requires_password(self):
        dialog = self._dialog()
        dialog.back_btn.click()
        self.repo.verify_exit.assert_not_called()
        self.assertEqual(self.results, [])

    def test_back_with_password_returns_back(self):
        dialog = self._dialog()
        dialog.password_input.setText("parol")
        dialog.back_btn.click()
        self.repo.verify_exit.assert_called_once_with(password="parol", purpose="back")
        self.assertEqual(self.results, [ExitDialog.BACK])

    def test_exit_with_password_returns_accepted(self):
        dialog = self._dialog()
        dialog.password_input.setText("parol")
        dialog.confirm_btn.click()
        self.repo.verify_exit.assert_called_once_with(password="parol", purpose="exit")
        self.assertEqual(self.results, [int(QDialog.DialogCode.Accepted.value)])

    def test_wrong_password_keeps_dialog_open(self):
        self.repo.verify_exit.side_effect = ClientError("Parol noto'g'ri", code="exit_password_invalid")
        dialog = self._dialog()
        dialog.password_input.setText("xato")
        dialog.back_btn.click()
        self.assertEqual(self.results, [])
        self.assertEqual(dialog.password_input.text(), "")

    def test_enter_is_the_safe_action(self):
        dialog = self._dialog()
        dialog.password_input.setText("parol")
        dialog.password_input.returnPressed.emit()
        self.repo.verify_exit.assert_called_once_with(password="parol", purpose="back")

        dialog = self._dialog(back=False)
        dialog.password_input.setText("parol")
        dialog.password_input.returnPressed.emit()
        self.assertEqual(self.repo.verify_exit.call_args.kwargs["purpose"], "exit")

    def test_unconfigured_password_allows_both(self):
        self.repo.verify_exit.side_effect = ClientError(
            "Sozlanmagan", code="exit_password_not_configured"
        )
        dialog = self._dialog()
        dialog.password_input.setText("nimadir")
        dialog.back_btn.click()  # server: parol sozlanmagan -> tasdiq rejimi
        self.assertEqual(self.results, [])
        dialog.back_btn.click()
        self.assertEqual(self.results, [ExitDialog.BACK])


if __name__ == "__main__":
    unittest.main()
