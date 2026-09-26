"""
Tayyorlik tekshiruvi: kamera tekshiruvi server MAJBURLAGANDA to'siq.

Ilgari "Kamera tekshiruvi o'tkazilmagan" doim ogohlantirish edi:
operator uni tasdiqlab o'tar, server esa `proctoring/start/` da
`camera_check_required` bilan rad etardi - talabgor FaceID va shaxs
tasdig'idan o'tib bo'lgach.
"""

import unittest

from proctoring.camera.roles import CameraLayout
from proctoring.policy import check_readiness

TITLE = "Kamera tekshiruvi o'tkazilmagan"


def _issue(camera: dict):
    config = {"proctoring": {"camera": camera, "modules": {}}}
    issues = check_readiness(config=config, layout=CameraLayout())
    return next(item for item in issues if item.title == TITLE)


class CameraCheckRequirementTests(unittest.TestCase):
    def test_required_by_server_blocks(self):
        self.assertTrue(_issue({"check_required": True, "primary_required": True}).blocking)

    def test_old_server_without_flag_only_warns(self):
        self.assertFalse(_issue({"primary_required": True}).blocking)

    def test_no_camera_needed_only_warns(self):
        """Server ham kamera talab qilinmasa tekshiruvsiz boshlashga ruxsat beradi."""
        issue = _issue(
            {"check_required": True, "primary_required": False, "secondary_required": False}
        )
        self.assertFalse(issue.blocking)


if __name__ == "__main__":
    unittest.main()
