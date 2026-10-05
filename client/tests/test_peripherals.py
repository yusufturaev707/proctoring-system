"""
Qo'shimcha qurilmalar kuzatuvi (`services/peripherals.py`, `DeviceWatcher`).

Windows API'siz: tugunlar va holatlar qo'lda yasaladi. Tugunlar shakli
haqiqiy mashinadan olingan (Logi C270 konteynerida Camera + AudioEndpoint,
fleshkada USB + DiskDrive + WPD + Volume).
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.system_events import classify_message  # noqa: E402
from services import peripherals as pp  # noqa: E402
from services.peripherals import DevNode, Peripheral, PeripheralTracker, Snapshot  # noqa: E402

FLASH = "{11111111-0000-0000-0000-000000000001}"
WEBCAM = "{22222222-0000-0000-0000-000000000002}"
HEADSET = "{33333333-0000-0000-0000-000000000003}"


def flash_nodes(container=FLASH):
    return [
        DevNode(r"USB\VID_0951&PID_1666\60A44C4138", "USB", "USB Mass Storage Device", container),
        DevNode(r"USBSTOR\DISK&VEN_KINGSTON\60A44C4138&0", "DiskDrive", "Kingston DataTraveler 3.0 USB Device", container),
        DevNode(r"SWD\WPDBUSENUM\_??_USBSTOR#DISK", "WPD", "KINGSTON", container),
        DevNode(r"STORAGE\VOLUME\_??_USBSTOR#DISK", "Volume", "Volume", container),
    ]


def device(container, kind, label="X"):
    return Peripheral(key=f"dev:{container}", kind=kind, label=label, source="device", container=container)


def drive(letter, serial=1, drive_type=2):
    key = f"drive:{letter}:{serial:08X}"
    return Peripheral(key=key, kind="storage", label=f"{letter}: FLASH", source="drive", drive_type=drive_type)


def audio(name, container=""):
    return Peripheral(key=f"audio:{name}", kind="audio", label=name, source="audio", container=container)


def snap(*items, failed=()):
    return Snapshot(items={item.key: item for item in items}, failed=set(failed))


class ClassifyTests(unittest.TestCase):
    def test_flash_is_storage_not_phone(self):
        kind, node = pp.classify(flash_nodes())
        self.assertEqual(kind, "storage")
        self.assertEqual(node.device_class, "DiskDrive")

    def test_volume_node_name_does_not_win(self):
        # Ventoy fleshka: Volume tuguni ("Том") ro'yxatda DiskDrive'dan oldin.
        nodes = [
            DevNode(r"STORAGE\VOLUME\_??_USBSTOR#DISK", "Volume", "Том", FLASH),
            DevNode(r"USBSTOR\DISK&VEN_VENTOY\X", "DiskDrive", "Ventoy USB Device", FLASH),
        ]
        self.assertEqual(pp.classify(nodes)[1].name, "Ventoy USB Device")

    def test_webcam_with_microphone_is_camera(self):
        nodes = [
            DevNode(r"USB\VID_046D&PID_0825\X", "USB", "USB Composite Device", WEBCAM),
            DevNode(r"USB\VID_046D&PID_0825&MI_00\X", "Camera", "Logi C270 HD WebCam", WEBCAM),
            DevNode(r"SWD\MMDEVAPI\{0.0.1.00000000}", "AudioEndpoint", "Mikrofon (Logi C270)", WEBCAM),
        ]
        kind, node = pp.classify(nodes)
        self.assertEqual((kind, node.name), ("camera", "Logi C270 HD WebCam"))

    def test_mtp_phone_and_iphone(self):
        self.assertEqual(pp.classify([DevNode(r"USB\VID_04E8&PID_6860\R58M", "WPD", "Galaxy A52")])[0], "phone")
        self.assertEqual(pp.classify([DevNode(r"USB\VID_05AC&PID_12A8\X", "Image", "Apple iPhone")])[0], "phone")

    def test_monitor_only_container_is_ignored(self):
        self.assertEqual(pp.classify([DevNode(r"DISPLAY\DELA0B1\X", "Monitor", "Dell")]), (None, None))


class GroupTests(unittest.TestCase):
    def test_flash_is_one_peripheral_with_usb_ids(self):
        items = pp.group_devices(flash_nodes())
        self.assertEqual(len(items), 1)
        item = items[f"dev:{FLASH}"]
        self.assertEqual((item.kind, item.vid, item.pid, item.serial), ("storage", "0951", "1666", "60A44C4138"))
        self.assertIn("Kingston", item.label)

    def test_internal_devices_are_skipped(self):
        nodes = [DevNode(r"USB\VID_04F2&PID_B6DD\X", "Camera", "Integrated Webcam", pp.ROOT_CONTAINER)]
        self.assertEqual(pp.group_devices(nodes), {})

    def test_paired_bluetooth_and_network_devices_are_skipped(self):
        # Juftlangan BT naushnik (ulanmagan ham "bor") va tarmoqdagi printer.
        nodes = [
            DevNode(r"BTHENUM\{0000110B}_VID&0001\X", "MEDIA", "WH-1000XM4", HEADSET),
            DevNode(r"SWD\PRINTENUM\{X}", "Printer", "HP LaserJet", WEBCAM),
        ]
        self.assertEqual(pp.group_devices(nodes), {})

    def test_port_trace_is_not_a_serial(self):
        self.assertEqual(pp.usb_ids(r"USB\VID_046D&PID_C52B\6&1E2AFDEC&0&2"), ("046D", "C52B", ""))


class AudioEndpointTests(unittest.TestCase):
    def test_internal_speakers_and_display_audio_are_skipped(self):
        self.assertIsNone(pp.audio_endpoint("{0.0.0.00000000}.{a}", "Speakers", 1, pp.ROOT_CONTAINER))
        self.assertIsNone(pp.audio_endpoint("{0.0.0.00000000}.{b}", "DELL (HDMI)", 9, WEBCAM))

    def test_jack_headphones_are_tracked(self):
        item = pp.audio_endpoint("{0.0.0.00000000}.{c}", "Headphones (Realtek)", 3, pp.ROOT_CONTAINER)
        self.assertEqual((item.kind, item.container), ("audio", ""))

    def test_usb_or_bluetooth_audio_keeps_container(self):
        item = pp.audio_endpoint("{0.0.1.00000000}.{d}", None, 4, HEADSET.upper())
        self.assertEqual(item.container, HEADSET)
        self.assertIn("mikrofon", item.label)


class TrackerStartTests(unittest.TestCase):
    def test_flash_present_at_start_is_one_event_with_drive(self):
        tracker = PeripheralTracker()
        events = tracker.start(snap(
            device(FLASH, "storage", "Kingston"), drive("E"), drive("C", 9, drive_type=3),
            device(WEBCAM, "camera"), device("{m}", "input"),
        ))
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual((event.type, event.severity), ("peripheral_connected", 3))
        self.assertTrue(event.payload["at_start"])
        self.assertEqual(event.payload["drives"], ["E: FLASH"])

    def test_usb_headset_audio_is_part_of_device(self):
        tracker = PeripheralTracker()
        events = tracker.start(snap(device(HEADSET, "audio", "USB Audio"), audio("Speakers", HEADSET)))
        self.assertEqual([e.payload["label"] for e in events], ["USB Audio"])


class TrackerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tracker = PeripheralTracker()
        self.tracker.start(snap(drive("C", 9, drive_type=3)))
        self.base = [drive("C", 9, drive_type=3)]

    def step(self, *items, now=0.0, failed=()):
        return self.tracker.update(snap(*self.base, *items, failed=failed), now)

    def test_flash_mid_exam_is_one_event_with_drive_then_removed(self):
        flash = device(FLASH, "storage", "Kingston")
        self.assertEqual(self.step(flash, now=1), [])           # tasdiq kutadi
        events = self.step(flash, drive("E"), now=2)            # tom ham ulandi
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["drives"], ["E: FLASH"])
        self.assertEqual(self.step(flash, drive("E"), now=3), [])
        removed = self.step(now=4)
        self.assertEqual([(e.type, e.payload["label"]) for e in removed], [("peripheral_removed", "Kingston")])

    def test_transient_node_is_not_reported(self):
        self.step(device(FLASH, "other"), now=1)
        self.assertEqual(self.step(now=2), [])
        self.assertFalse(self.tracker.has_pending)

    def test_phone_without_drive_letter_is_reported_after_wait(self):
        phone = device(FLASH, "phone", "Galaxy")
        results = [self.step(phone, now=n) for n in range(1, 5)]
        self.assertEqual([len(r) for r in results], [0, 0, 0, 1])

    def test_sd_card_in_internal_reader_is_drive_only(self):
        self.step(drive("F"), now=1)
        events = self.step(drive("F"), now=2)
        self.assertEqual([(e.payload["source"], e.payload["label"]) for e in events], [("drive", "F: FLASH")])

    def test_late_drive_letter_is_attached_silently(self):
        flash = device(FLASH, "storage", "Kingston")
        for n in range(1, 5):
            self.step(flash, now=n)
        self.assertEqual(self.step(flash, drive("E"), now=5), [])
        self.assertEqual(self.step(flash, drive("E"), now=6), [])

    def test_jack_headphones_and_usb_headset(self):
        jack = audio("Headphones (Realtek)")
        self.step(jack, now=1)
        self.assertEqual(len(self.step(jack, now=2)), 1)
        headset = device(HEADSET, "audio", "USB Audio")
        speakers = audio("Speakers (USB)", HEADSET)
        self.step(jack, headset, speakers, now=3)
        events = self.step(jack, headset, speakers, now=4)
        self.assertEqual([e.payload["label"] for e in events], ["USB Audio"])

    def test_failed_source_is_not_removal(self):
        flash = device(FLASH, "storage")
        self.step(flash, drive("E"), now=1)
        self.step(flash, drive("E"), now=2)
        # Disklar manbai bu safar o'qilmadi - E: "uzildi" EMAS.
        self.assertEqual(self.tracker.update(snap(flash, failed={"drive"}), 3), [])

    def test_source_failed_at_start_gets_silent_baseline(self):
        tracker = PeripheralTracker()
        tracker.start(snap(failed={"audio"}))
        speakers = audio("Headphones (Realtek)")
        self.assertEqual(tracker.update(snap(speakers), 1), [])
        self.assertEqual(tracker.update(snap(speakers), 2), [])

    def test_mouse_is_low_severity_and_removal_is_info(self):
        mouse = device("{m}", "input", "USB mouse")
        self.step(mouse, now=1)
        self.assertEqual(self.step(mouse, now=2)[0].severity, 1)
        self.assertEqual(self.step(now=3)[0].severity, 0)


class SystemEventsTests(unittest.TestCase):
    def test_device_change_messages(self):
        self.assertEqual(classify_message(0x0219, 0x0007), "devices")
        self.assertEqual(classify_message(0x0219, 0x8000), "devices")
        self.assertEqual(classify_message(0x0219, 0x0018), "")


class WatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _watcher(self):
        from services.device_watch import DeviceWatcher

        watcher = DeviceWatcher()
        self.addCleanup(watcher.stop)
        return watcher

    def test_old_server_without_key_does_not_start_scanner(self):
        # Eski server `peripheral_*` ni bilmaydi va butun batch'ni rad etardi.
        watcher = self._watcher()
        config = {"device": {"detect_monitor": False}, "rdp": {"enabled": False}}
        with mock.patch("services.device_watch._PeripheralScanner") as scanner:
            watcher.start(config)
        scanner.assert_not_called()

    def test_enabled_by_server_starts_scanner(self):
        watcher = self._watcher()
        config = {"device": {"detect_monitor": False, "detect_peripherals": True}, "rdp": {"enabled": False}}
        with mock.patch("services.device_watch._PeripheralScanner") as scanner:
            watcher.start(config)
        scanner.return_value.start.assert_called_once()
        watcher._peripherals = None  # soxta skaner - `stop` unga tegmasin

    def test_events_are_logged_and_emitted(self):
        watcher = self._watcher()
        watcher._active = True
        emitted = []
        watcher.detected.connect(lambda kind, sev, payload: emitted.append((kind, sev, payload)))
        event = PeripheralTracker._event("connected", device(FLASH, "storage", "Kingston"), drives=["E: X"])
        with self.assertLogs("services.device_watch", "WARNING") as logs:
            watcher._on_peripherals([event])
        self.assertEqual(emitted[0][:2], ("peripheral_connected", 3))
        self.assertIn("Kingston", logs.output[0])
        watcher._active = False


if __name__ == "__main__":
    unittest.main()
