"""
Redis Stream -> PostgreSQL yozuv qatlami.

Bu qatlamning yagona vazifasi — **hodisa yo'qolmasligi**. Shuning
uchun testlar "yaxshi kun"ni emas, aynan nosozliklarni qamrab oladi:

  * batch ichida bitta buzuq qator bo'lsa, yaxshilari YOZILADI;
  * yozib bo'lmagan qator jimgina tashlanmaydi — `:dead` oqimiga
    ko'chiriladi;
  * ikkala holatda ham yozuv ACK qilinadi, aks holda buzuq qator
    oqimni ABADIY to'sib qo'yardi.
"""

from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from apps.common.redis_client import get_redis
from apps.common.tests.utils import RedisStateMixin
from apps.proctoring.models import ProctoringEvent
from apps.proctoring.services import stream as stream_service
from apps.proctoring.tasks import flush_event_buffer
from apps.proctoring.tests import factories

STREAM = "test:events"


class WriteWithFallbackTests(TestCase):
    def setUp(self):
        self.session = factories.make_session()

    def _row(self, entry_id, *, event_type=None):
        return (
            entry_id,
            {"session_id": str(self.session.pk)},
            ProctoringEvent(
                session_id=self.session.pk,
                type=event_type or ProctoringEvent.Type.WINDOW_BLUR,
                severity=1,
                occurred_at=timezone.now(),
            ),
        )

    def _bad_row(self, entry_id):
        """
        DARHOL xato beradigan qator.

        Mavjud bo'lmagan `session_id` bu yerda YARAMAYDI: Django FK
        cheklovlarini `DEFERRABLE INITIALLY DEFERRED` qilib yaratadi,
        ya'ni buzilish INSERT paytida emas, tranzaksiya commit'ida
        chiqadi — `write_with_fallback` uni umuman ko'rmaydi.
        Uzunlik chegarasi esa (`type` — `varchar(32)`) darhol xato
        beradi va aynan shu real hayotdagi holatga o'xshaydi: buzilgan
        yoki eskirgan client noto'g'ri qiymat yuboradi.
        """
        return self._row(entry_id, event_type="x" * 100)

    def test_happy_path_writes_everything_in_one_batch(self):
        rows = [self._row(f"1-{i}") for i in range(5)]
        result = stream_service.write_with_fallback(ProctoringEvent, rows, STREAM)

        self.assertEqual(len(result["ok"]), 5)
        self.assertEqual(result["dead"], 0)
        self.assertEqual(ProctoringEvent.objects.count(), 5)

    def test_empty_rows(self):
        result = stream_service.write_with_fallback(ProctoringEvent, [], STREAM)
        self.assertEqual(result, {"ok": [], "dead": 0})

    def test_one_bad_row_does_not_lose_the_others(self):
        """
        `bulk_create` butun batchni yiqitadi, shuning uchun yiqilgandan
        keyin qator-ma-qator o'tiladi: yaxshi qatorlar yoziladi, yomoni
        ajratiladi.
        """
        rows = [self._row("1-0"), self._bad_row("1-1"), self._row("1-2")]
        result = stream_service.write_with_fallback(ProctoringEvent, rows, STREAM)

        self.assertEqual(ProctoringEvent.objects.count(), 2)
        self.assertEqual(result["dead"], 1)
        # Uchalasi ham ACK qilinadi: dead-letter'ga ketgani ham oqimni
        # to'sib turmasligi kerak.
        self.assertEqual(result["ok"], ["1-0", "1-1", "1-2"])

    def test_bad_row_is_moved_to_dead_letter(self):
        rows = [self._bad_row("1-0")]
        with mock.patch.object(stream_service, "to_dead_letter") as dead:
            stream_service.write_with_fallback(ProctoringEvent, rows, STREAM)
        dead.assert_called_once()
        self.assertEqual(dead.call_args.args[0], STREAM)

    def test_duplicates_are_ignored_not_failed(self):
        """
        `client_event_id` bo'yicha dublikat - NORMAL holat.

        Client tarmoq uzilishidan keyin buferini qayta yuboradi;
        `ignore_conflicts=True` uni jimgina tashlab yuboradi.
        """
        first = self._row("1-0")
        first[2].client_event_id = "abc"
        stream_service.write_with_fallback(ProctoringEvent, [first], STREAM)

        second = self._row("1-1")
        second[2].client_event_id = "abc"
        result = stream_service.write_with_fallback(ProctoringEvent, [second], STREAM)

        self.assertEqual(result["dead"], 0)
        self.assertEqual(ProctoringEvent.objects.count(), 1)


class DeadLetterTests(RedisStateMixin, TestCase):
    def test_writes_to_dead_stream(self):
        stream_service.to_dead_letter(STREAM, {"a": "b"}, "sinov sababi")
        entries = get_redis().xrange(stream_service.dead_letter_key(STREAM))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][1]["reason"], "sinov sababi")

    def test_survives_redis_failure(self):
        """
        Dead-letter — oxirgi himoya qatlami va u O'ZI yiqilmasligi kerak.

        Redis tushgan bo'lsa ham istisno chiqarmaydi, aks holda u
        chaqirilgan joydagi (ingest) oqimni to'xtatardi.
        """
        with mock.patch.object(
            stream_service, "get_redis", side_effect=RuntimeError("o'chgan")
        ):
            stream_service.to_dead_letter(STREAM, {"a": "b"}, "sabab")

    def test_payload_is_truncated(self):
        stream_service.to_dead_letter(STREAM, {"a": "x" * 20_000}, "r" * 2_000)
        entries = get_redis().xrange(stream_service.dead_letter_key(STREAM))
        fields = entries[0][1]
        self.assertLessEqual(len(fields["reason"]), 500)
        self.assertLessEqual(len(fields["payload"]), 8_000)


class ConsumerGroupTests(RedisStateMixin, TestCase):
    def test_consumer_name_is_unique_per_process(self):
        """
        Har bir worker o'z nomi ostida o'qiydi.

        Umumiy nom ostida PEL bitta joyda yig'iladi va yiqilgan
        process qaysi yozuvlarni ushlab qolganini ajratib bo'lmaydi.
        """
        import os

        self.assertIn(str(os.getpid()), stream_service.consumer_name())

    def test_ensure_group_is_idempotent(self):
        client = get_redis()
        stream_service.ensure_group(client, STREAM)
        stream_service.ensure_group(client, STREAM)  # BUSYGROUP yutiladi

    def test_read_batch_returns_new_entries(self):
        client = get_redis()
        client.xadd(STREAM, {"a": "1"})
        client.xadd(STREAM, {"a": "2"})

        entries = stream_service.read_batch(client, STREAM, 10)
        self.assertEqual(len(entries), 2)

    def test_acked_entries_are_not_returned_again(self):
        client = get_redis()
        client.xadd(STREAM, {"a": "1"})

        entries = stream_service.read_batch(client, STREAM, 10)
        stream_service.ack(client, STREAM, [entry_id for entry_id, _ in entries])

        self.assertEqual(stream_service.read_batch(client, STREAM, 10), [])


class FlushEventBufferTests(RedisStateMixin, TestCase):
    """`flush_event_buffer` — Celery vazifasi uchidan-uchiga."""

    def setUp(self):
        super().setUp()
        self.session = factories.make_session()
        self.stream = settings.PROCTORING["EVENT_STREAM_KEY"]

    def _push(self, **overrides):
        get_redis().xadd(
            self.stream,
            {
                "session_id": str(self.session.pk),
                "zone_id": "0",
                "type": ProctoringEvent.Type.WINDOW_BLUR,
                "severity": "1",
                "occurred_at": timezone.now().isoformat(),
                "payload": "{}",
                "screenshot_key": "",
                "client_event_id": "",
                **overrides,
            },
        )

    def test_empty_stream(self):
        self.assertEqual(flush_event_buffer(), {"read": 0, "written": 0, "dead": 0})

    def test_writes_events_to_database(self):
        for _ in range(3):
            self._push()
        result = flush_event_buffer()

        self.assertEqual(result["read"], 3)
        self.assertEqual(result["written"], 3)
        self.assertEqual(ProctoringEvent.objects.count(), 3)

    def test_malformed_record_goes_to_dead_letter_and_is_acked(self):
        """
        Model obyektiga aylantirib bo'lmagan yozuv oqimni TO'SMAYDI.

        Aks holda bitta buzuq yozuv butun ingest'ni abadiy to'xtatardi.
        """
        self._push(occurred_at="umuman-vaqt-emas", severity="ha")
        self._push()

        result = flush_event_buffer()

        self.assertEqual(result["dead"], 1)
        self.assertEqual(ProctoringEvent.objects.count(), 1)
        # Ikkinchi yurishda oqim bo'sh — buzuq yozuv qaytib kelmaydi.
        self.assertEqual(flush_event_buffer()["read"], 0)

        dead = get_redis().xrange(stream_service.dead_letter_key(self.stream))
        self.assertEqual(len(dead), 1)
