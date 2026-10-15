"""
`:dead` oqimi: tasnif, qayta yozish va zaxira bilan tozalash
(`services/dead_letters.py`, `manage.py dead_letters`).

Asosiy kafolat — hech narsa jimgina yo'qolmaydi: qayta yozish yozuvni
asosiy oqimga qo'ygandan KEYIN o'chiradi, tozalash esa faylga
yozgandan KEYIN.
"""

import json
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.common.redis_client import get_redis
from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import ProctoringEvent
from apps.proctoring.services import dead_letters
from apps.proctoring.services import stream as stream_service
from apps.proctoring.tasks import flush_event_buffer
from apps.proctoring.tests import factories


def _event_fields(session_id, client_event_id="e1"):
    return {
        "session_id": str(session_id),
        "zone_id": "",
        "type": ProctoringEvent.Type.WINDOW_BLUR,
        "severity": "1",
        "occurred_at": timezone.now().isoformat(),
        "payload": "{}",
        "screenshot_key": "",
        "client_event_id": client_event_id,
    }


class _FakePgError(Exception):
    """psycopg2 xatosi shakli: `pgcode` va `diag.constraint_name`."""

    pgcode = "23503"
    diag = SimpleNamespace(constraint_name="proctoring_event_session_fk")


def _fk_error() -> IntegrityError:
    """Django `IntegrityError`, sababi (`__cause__`) — psycopg xatosi."""
    error = IntegrityError("fk")
    error.__cause__ = _FakePgError("fk")
    return error


class ClassifyTests(SimpleTestCase):
    def test_by_sqlstate(self):
        self.assertEqual(
            dead_letters.classify({"code": "23503", "constraint": "proctoring_event_session_fk", "reason": "..."}),
            "session_missing",
        )
        self.assertEqual(dead_letters.classify({"code": "23514", "constraint": "", "reason": "..."}), "no_partition")
        self.assertEqual(dead_letters.classify({"code": "22001", "reason": "..."}), "invalid_data")
        self.assertEqual(dead_letters.classify({"code": "08006", "reason": "..."}), "db_unavailable")

    def test_named_check_constraint_is_not_partition(self):
        self.assertEqual(
            dead_letters.classify({"code": "23514", "constraint": "booking_pinfl_required", "reason": "x"}), "other",
        )

    def test_legacy_localized_text_uses_constraint_name(self):
        """Eski yozuv: ruscha (buzilgan) matn, lekin cheklov nomi ASCII."""
        reason = '������: INSERT ... "proctoring_event_session_fk" DETAIL: (session_id)=(47)'
        self.assertEqual(dead_letters.classify({"reason": reason}), "session_missing")

    def test_parse(self):
        self.assertEqual(dead_letters.classify({"reason": "parse: 'type'"}), "parse")


class DeadLetterServiceTests(RedisStateMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.stream = settings.PROCTORING["EVENT_STREAM_KEY"]
        self.dead = stream_service.dead_letter_key(self.stream)
        self.session = factories.make_session()

    def test_fk_failure_records_sqlstate_and_constraint(self):
        """
        Yangi yozuvlarda tilga bog'liq bo'lmagan belgilar saqlanadi.

        FK xatosi soxtalashtiriladi: Django FK'lari `DEFERRABLE INITIALLY
        DEFERRED` va `TestCase` savepoint ichida — haqiqiy xato faqat
        commit'da (Celery flush'da shunday) chiqardi.
        """
        get_redis().xadd(self.stream, _event_fields(self.session.pk))
        with mock.patch.object(ProctoringEvent.objects, "bulk_create", side_effect=_fk_error()):
            flush_event_buffer()

        (_entry_id, entry), = get_redis().xrange(self.dead)
        self.assertEqual(entry["code"], "23503")
        self.assertEqual(entry["constraint"], "proctoring_event_session_fk")
        self.assertEqual(dead_letters.classify(entry), "session_missing")

    def test_replay_writes_event_and_removes_dead_entry(self):
        stream_service.to_dead_letter(self.stream, _event_fields(self.session.pk), "connection refused")

        result = dead_letters.replay("events")
        self.assertEqual(result["replayed"], 1)
        self.assertEqual(get_redis().xlen(self.dead), 0)

        flush_event_buffer()
        self.assertTrue(ProctoringEvent.objects.filter(session=self.session, client_event_id="e1").exists())

    def test_replay_never_requeues_missing_session(self):
        stream_service.to_dead_letter(self.stream, _event_fields(self.session.pk + 10_000), "boshqa xato")

        result = dead_letters.replay("events", categories={"other"})
        self.assertEqual(result["replayed"], 0)
        self.assertEqual(result["skipped"], {"session_missing": 1})
        self.assertEqual(get_redis().xlen(self.dead), 1)

    def test_dry_run_changes_nothing(self):
        stream_service.to_dead_letter(self.stream, _event_fields(self.session.pk), "connection refused")
        self.assertEqual(dead_letters.replay("events", dry_run=True)["replayed"], 1)
        self.assertEqual(get_redis().xlen(self.dead), 1)
        self.assertFalse(get_redis().exists(self.stream))

    def test_immediate_path_record_with_dict_payload(self):
        """Tezkor yo'l yozuvida `payload` dict bo'lishi mumkin — XADD uchun satrga."""
        fields = {**_event_fields(self.session.pk), "payload": {"a": 1}}
        stream_service.to_dead_letter(self.stream, fields, "immediate: server closed the connection")
        self.assertEqual(dead_letters.replay("events")["replayed"], 1)
        (_id, queued), = get_redis().xrange(self.stream)
        self.assertEqual(json.loads(queued["payload"]), {"a": 1})

    def test_purge_writes_backup_before_deleting(self):
        stream_service.to_dead_letter(
            self.stream, _event_fields(999_999), 'insert ... "proctoring_event_session_fk"',
        )
        stream_service.to_dead_letter(self.stream, _event_fields(self.session.pk), "connection refused")
        output = Path(tempfile.mkdtemp()) / "backup.jsonl"

        result = dead_letters.purge("events", categories={"session_missing"}, output=output)

        self.assertEqual(result["deleted"], 1)
        lines = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["category"], "session_missing")
        self.assertEqual(get_redis().xlen(self.dead), 1)  # boshqa turkum tegilmadi

    def test_purge_keeps_entries_if_backup_fails(self):
        stream_service.to_dead_letter(self.stream, _event_fields(999_999), "proctoring_event_session_fk")
        with mock.patch.object(Path, "open", side_effect=OSError("disk to'la")):
            with self.assertRaises(OSError):
                dead_letters.purge("events", categories={"session_missing"}, output=Path(tempfile.mkdtemp()) / "x.jsonl")
        self.assertEqual(get_redis().xlen(self.dead), 1)

    def test_command_stats_and_purge_requires_confirmation(self):
        stream_service.to_dead_letter(self.stream, _event_fields(999_999), "proctoring_event_session_fk")
        out = StringIO()
        call_command("dead_letters", "stats", stdout=out)
        self.assertIn("session_missing", out.getvalue())

        out = StringIO()
        call_command("dead_letters", "purge", "--category", "session_missing", stdout=out)
        self.assertIn("--yes", out.getvalue())
        self.assertEqual(get_redis().xlen(self.dead), 1)


class ErrorDetailsTests(SimpleTestCase):
    def test_reads_pgcode_from_cause(self):
        self.assertEqual(
            stream_service.error_details(_fk_error()),
            {"error": "IntegrityError", "code": "23503", "constraint": "proctoring_event_session_fk"},
        )


class PurgeAllCommandTests(RedisStateMixin, TestCase):
    def test_purge_all_empties_stream_with_backup(self):
        stream = settings.PROCTORING["EVENT_STREAM_KEY"]
        stream_service.to_dead_letter(stream, _event_fields(999_999), "proctoring_event_session_fk")
        stream_service.to_dead_letter(stream, _event_fields(1), "connection refused")
        backup = Path(tempfile.mkdtemp())
        out = StringIO()
        with mock.patch.object(dead_letters, "backup_dir", return_value=backup):
            call_command("dead_letters", "purge", "--all", "--yes", stdout=out)
        self.assertEqual(get_redis().xlen(stream_service.dead_letter_key(stream)), 0)
        self.assertEqual(len(next(backup.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()), 2)
