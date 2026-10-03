"""
Masofaviy seans va virtual mashina aniqlash (`process_identity`,
`threat_scanner`).

Qo'riqlanadigan narsalar:

  1. VM belgisi 7 ta BIOS maydonidan olinadi va qisqa belgilar ("xen",
     "kvm") faqat BUTUN SO'Z sifatida - haqiqiy mashinada soxta "virtual
     mashina" to'sig'i butun imtihonni to'xtatardi;
  2. begona RDP seansi imtihondan TASHQARIDA faqat qayd etiladi va
     to'sadi, imtihon DAVOMIDA esa yakunlanadi; yakunlab bo'lmasa to'siq
     qoladi;
  3. o'z seansimiz hech qachon yakunlanmaydi.
"""

import unittest
from unittest import mock

from services import process_identity as pi
from services import threat_scanner as ts


class VmMarkerTests(unittest.TestCase):
    def test_detects_hypervisors_in_any_field(self):
        cases = {
            "virtual machine (SystemProductName)": {"SystemProductName": "Virtual Machine"},
            "hyper-v (BIOSVersion)": {"BIOSVersion": "Hyper-V UEFI Release v4.1"},
            "virtualbox (SystemFamily)": {"SystemFamily": "VirtualBox"},
            "vmware (BaseBoardProduct)": {"BaseBoardProduct": "VMware Virtual Platform"},
            "xen (BIOSVersion)": {"BIOSVersion": "4.11.amazon Xen"},
            "qemu (SystemManufacturer)": {"SystemManufacturer": "QEMU"},
        }
        for expected, values in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(pi.detect_vm_marker(values), expected)

    def test_short_markers_need_whole_word(self):
        real = {
            "SystemManufacturer": "Dell Inc.",
            "SystemProductName": "OptiPlex 7090",
            "BaseBoardProduct": "Xenomorph X570",
            "BIOSVersion": "1.9.0 SKVMX",
        }
        self.assertEqual(pi.detect_vm_marker(real), "")
        self.assertEqual(pi.detect_vm_marker({}), "")
        self.assertEqual(pi.detect_vm_marker(None), "")


class WtsParsingTests(unittest.TestCase):
    def test_text_and_address(self):
        self.assertEqual(pi._text("DOM\x00".encode("utf-16-le")), "DOM")
        self.assertEqual(pi._text(b""), "")
        raw = (2).to_bytes(4, "little") + bytes([0, 0, 10, 0, 0, 5]) + bytes(14)
        self.assertEqual(pi._client_ip(raw), "10.0.0.5")
        self.assertEqual(pi._client_ip((23).to_bytes(4, "little") + bytes(20)), "")
        self.assertEqual(pi._client_ip(None), "")

    def test_own_session_is_never_logged_off(self):
        ok, _reason = pi.logoff_session(pi._own_session_id())
        self.assertFalse(ok)
        self.assertFalse(pi.logoff_session(0)[0])


class ForeignRdpScanTests(unittest.TestCase):
    """Skanerni jarayon qismisiz - faqat muhit savollari."""

    def setUp(self):
        for target, value in (
            ("_scan_services", None),
            ("_scan_processes", None),
            ("_listening_ports", {}),
            ("_own_pids", set()),
            ("in_remote_session", False),
            ("host_virtualization", ""),
        ):
            patcher = mock.patch.object(ts, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            ts, "foreign_rdp_sessions",
            return_value=[pi.RdpSession(3, "DOM\\helper", "HOME-PC", "10.0.0.5")],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def finding(self, report):
        self.assertEqual(len(report.findings), 1)
        return report.findings[0]

    def test_found_and_blocking(self):
        item = self.finding(ts.scan())
        self.assertEqual((item.code, item.kind, item.session_id), ("rdp_foreign_session", "rdp_session", 3))
        self.assertTrue(item.blocking)
        self.assertIn("HOME-PC", item.evidence)

    def test_outside_exam_only_reports(self):
        report = ts.scan()
        with mock.patch.object(ts, "logoff_session") as logoff:
            ts.neutralize(report)
        logoff.assert_not_called()
        self.assertEqual(report.survivors, report.findings)
        self.assertIn("operator", report.findings[0].reason)

    def test_during_exam_session_is_ended(self):
        report = ts.scan()
        with mock.patch.object(ts, "logoff_session", return_value=(True, "")) as logoff:
            ts.neutralize(report, end_rdp_sessions=True)
        logoff.assert_called_once_with(3)
        self.assertEqual(report.survivors, [])
        severity = report.events()[0][1]
        self.assertEqual(severity, 3)  # yo'q qilingan - YUQORI, kritik emas

    def test_failed_logoff_keeps_exam_blocked(self):
        report = ts.scan()
        with mock.patch.object(ts, "logoff_session", return_value=(False, "huquq yetmadi (administrator kerak)")):
            ts.neutralize(report, end_rdp_sessions=True)
        self.assertEqual(len(report.survivors), 1)
        self.assertEqual(report.events()[0][1], 4)
        self.assertIn("administrator", report.findings[0].reason)

    def test_allow_list_skips(self):
        self.assertEqual(ts.scan(allow=["rdp_foreign_session"]).findings, [])


class NeutralizeAccessDeniedTests(unittest.TestCase):
    """
    Administrator huquqisiz SYSTEM jarayoni (`remoting_host.exe`).

    `psutil.wait_procs` bunday jarayonni ocholmaydi va `AccessDenied`
    bilan yiqiladi; ilgari shu istisno butun hisobotni yo'qotib,
    Chrome Remote Desktop imtihonni to'smasdan o'tib ketardi.
    """

    def report(self):
        finding = ts.Finding(
            code="chrome_remote_desktop", label="Chrome Remote Desktop",
            category="remote", blocking=True, kind="process",
            pid=7152, name="remoting_host.exe",
        )
        return ts.ThreatReport(findings=[finding], elevated=False)

    def test_unkillable_process_survives_and_blocks(self):
        import psutil

        process = mock.Mock()
        process.kill.side_effect = psutil.AccessDenied(pid=7152)
        report = self.report()
        with mock.patch.object(psutil, "Process", return_value=process), \
                mock.patch.object(psutil, "wait_procs", side_effect=psutil.AccessDenied(pid=7152)) as wait:
            ts.neutralize(report)
        wait.assert_not_called()
        self.assertEqual(report.survivors, report.findings)
        self.assertIn("administrator", report.findings[0].reason)
        self.assertEqual(report.events()[0][1], 4)

    def test_wait_failure_does_not_lose_result(self):
        import psutil

        process = mock.Mock()
        process.is_running.return_value = False
        report = self.report()
        with mock.patch.object(psutil, "Process", return_value=process), \
                mock.patch.object(psutil, "wait_procs", side_effect=psutil.AccessDenied(pid=7152)):
            ts.neutralize(report)
        self.assertTrue(report.findings[0].neutralized)

    def test_sweep_keeps_report_when_neutralize_fails(self):
        report = self.report()
        with mock.patch.object(ts, "scan", side_effect=[report, self.report()]), \
                mock.patch.object(ts, "neutralize", side_effect=RuntimeError("boom")):
            result = ts.sweep()
        self.assertIs(result, report)
        self.assertEqual(len(result.survivors), 1)
