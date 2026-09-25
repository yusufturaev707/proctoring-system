"""
Xavf balli: to'planish, pasayish, takror hisoblash va tushuntirish.

Ilgari ball oddiy hisoblagich edi va uchta narsa yo'q edi. Bu
testlar aynan o'sha uchtasini himoya qiladi, chunki ularning
yo'qligi JIMGINA buziladi: ball baribir bir son bo'lib turadi,
faqat u noto'g'ri bo'ladi.
"""

from django.core.cache import cache
from django.test import TestCase

from apps.common.tests.utils import RedisStateMixin
from apps.controls.models import EventRiskWeight
from apps.proctoring.services import risk as risk_service
from apps.proctoring.tests import factories

CONFIG = {"decay_per_min": 5, "cooldown_s": 60, "low": 20, "medium": 40, "high": 70}


class ConfigTests(TestCase):
    def test_defaults_match_the_policy_defaults(self):
        """
        Siyosatsiz standartlar `_default_proctoring` bilan bir xil
        bo'lishi SHART - aks holda sozlanmagan tizim client va
        server tomonda boshqacha ishlardi.
        """
        from apps.controls.services import _default_proctoring

        resolved = risk_service.resolve_config(None)
        expected = _default_proctoring()["risk"]

        self.assertEqual(resolved["decay_per_min"], expected["decay_per_min"])
        self.assertEqual(resolved["cooldown_s"], expected["cooldown_s"])
        self.assertEqual(resolved["high"], expected["high"])

    def test_level_thresholds(self):
        self.assertEqual(risk_service.level(0, CONFIG), "normal")
        self.assertEqual(risk_service.level(19, CONFIG), "normal")
        self.assertEqual(risk_service.level(20, CONFIG), "low")
        self.assertEqual(risk_service.level(45, CONFIG), "medium")
        self.assertEqual(risk_service.level(70, CONFIG), "high")


class WeightTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_database_weight_wins(self):
        EventRiskWeight.objects.create(event_type="looking_away", weight=42)
        self.assertEqual(risk_service.weight_for("looking_away"), 42)

    def test_falls_back_to_code_when_table_is_empty(self):
        """
        Bo'sh jadval "og'irlik yo'q" degani EMAS.

        Sozlanmagan tizim ballni umuman hisoblamasa, chetlashtirish
        qarori asossiz qolardi.
        """
        from apps.proctoring.services.ingest import RISK_WEIGHTS

        self.assertEqual(
            risk_service.weight_for("multiple_faces"),
            RISK_WEIGHTS["multiple_faces"],
        )

    def test_unknown_event_gets_minimal_weight(self):
        self.assertEqual(risk_service.weight_for("umuman_boshqa_narsa"), 1)

    def test_inactive_row_is_ignored(self):
        EventRiskWeight.objects.create(
            event_type="looking_away", weight=99, is_active=False
        )
        from apps.proctoring.services.ingest import RISK_WEIGHTS

        self.assertNotEqual(risk_service.weight_for("looking_away"), 99)


class CooldownResolutionTests(TestCase):
    """
    Ustuvorlik: turga berilgan qiymat (>0) -> siyosatdagi umumiy qiymat.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_per_type_value_wins(self):
        EventRiskWeight.objects.create(event_type="window_blur", weight=2, cooldown_s=180)
        self.assertEqual(risk_service.cooldown_for("window_blur", CONFIG), 180)

    def test_zero_falls_back_to_policy(self):
        EventRiskWeight.objects.create(event_type="window_blur", weight=2, cooldown_s=0)
        self.assertEqual(risk_service.cooldown_for("window_blur", CONFIG), 60)

    def test_missing_row_falls_back_to_policy(self):
        self.assertEqual(risk_service.cooldown_for("looking_away", CONFIG), 60)

    def test_per_type_value_wins_over_disabled_policy(self):
        """
        Siyosatda cooldown o'chirilgan (0) bo'lsa ham, aniq tur uchun
        qo'yilgan qiymat ishlaydi - u ongli ravishda qo'yilgan qaror.
        """
        EventRiskWeight.objects.create(event_type="window_blur", weight=2, cooldown_s=30)
        self.assertEqual(
            risk_service.cooldown_for("window_blur", {**CONFIG, "cooldown_s": 0}), 30
        )

    def test_inactive_row_is_ignored(self):
        EventRiskWeight.objects.create(
            event_type="window_blur", weight=2, cooldown_s=180, is_active=False
        )
        self.assertEqual(risk_service.cooldown_for("window_blur", CONFIG), 60)


class ScoringTests(RedisStateMixin, TestCase):
    """
    Xom Redis bilan ishlaydi — `RedisStateMixin` uni 15-bazada
    tozalaydi va Redis yo'q mashinada testni o'tkazib yuboradi.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.session = factories.make_session()

    def add(self, event_type, *, now, weight=None):
        return risk_service.apply(
            session_id=self.session.pk,
            event_type=event_type,
            config=CONFIG,
            weight=weight,
            now=now,
        )

    # ------------------------------------------------------------------
    def test_score_accumulates(self):
        self.assertEqual(self.add("looking_away", now=1000.0, weight=5), 5)
        self.assertEqual(self.add("multiple_faces", now=1000.0, weight=20), 25)

    def test_cooldown_blocks_repeat(self):
        """
        Kamera burchagi noto'g'ri bo'lgani uchun yuz vaqti-vaqti
        bilan yo'qolsa, har yo'qolish ball qo'shmasligi kerak —
        TEXNIK nosozlik talabgorning aybiga aylanmasin.

        Tekshiruv TARKIB bo'yicha, ball bo'yicha emas: ball ayni
        paytda pasayib ham turadi va ikkala ta'sirni bitta sonda
        ajratib bo'lmasdi.
        """
        no_decay = {**CONFIG, "decay_per_min": 0}

        def add(now):
            return risk_service.apply(
                session_id=self.session.pk,
                event_type="face_not_found",
                config=no_decay,
                weight=6,
                now=now,
            )

        self.assertEqual(add(1000.0), 6)
        # Oyna ICHIDA - qo'shilmaydi.
        self.assertEqual(add(1030.0), 6)

        # Oynaning tugashi SOXTA VAQT bilan simulyatsiya qilinmaydi:
        # cooldown Redis TTL'ida yashaydi (atomik `SET NX`) va u
        # haqiqiy soatga bog'langan - `now` parametri unga ta'sir
        # qilmaydi. Shuning uchun kalit qo'lda o'chiriladi.
        from apps.common.redis_client import get_redis

        get_redis().delete(
            risk_service.cooldown_key(self.session.pk, "face_not_found")
        )
        self.assertEqual(add(1061.0), 12)
        self.assertEqual(
            risk_service.breakdown(self.session.pk), {"face_not_found": 12}
        )

    def test_blocked_event_still_reaches_the_log(self):
        """
        Cooldown BALLNI to'sadi, HODISANI emas.

        Hodisa dalil: u yozilishi shart, aks holda bayonnomada
        "yuz 40 marta yo'qoldi" degan fakt yo'qolardi. Cooldown
        faqat ballning ikki marta sanalishiga qarshi.
        """
        self.add("face_not_found", now=1000.0, weight=6)
        before = risk_service.breakdown(self.session.pk)["face_not_found"]
        self.add("face_not_found", now=1010.0, weight=6)
        after = risk_service.breakdown(self.session.pk)["face_not_found"]
        self.assertEqual(before, after)

    def test_cooldown_is_per_event_type(self):
        self.add("looking_away", now=1000.0, weight=5)
        # Boshqa tur - o'z oynasiga ega.
        self.assertEqual(self.add("multiple_faces", now=1000.0, weight=20), 25)

    def test_per_type_cooldown_reaches_redis(self):
        """
        Turga berilgan cooldown haqiqatan Redis TTL'iga yetib boradi.

        Ilgari `EventRiskWeight.cooldown_s` saqlanar, panelda
        ko'rsatilar, lekin hech qayerda o'qilmasdi - administrator uni
        o'zgartirib, hech narsa o'zgarmaganini ko'rardi.
        """
        from apps.common.redis_client import get_redis

        EventRiskWeight.objects.create(event_type="window_blur", weight=2, cooldown_s=180)
        self.add("window_blur", now=1000.0)

        ttl = get_redis().ttl(risk_service.cooldown_key(self.session.pk, "window_blur"))
        self.assertGreater(ttl, 60)
        self.assertLessEqual(ttl, 180)

    def test_score_decays_over_time(self):
        """
        Imtihon boshida bir marta chalg'igan talabgor uch soat
        davomida o'sha ball bilan yurmasligi kerak.
        """
        self.add("high_suspicion_phone", now=1000.0, weight=40)
        self.assertEqual(
            risk_service.current(session_id=self.session.pk, config=CONFIG, now=1000.0),
            40,
        )
        # 4 daqiqa x 5 ball = 20 ball pasayadi.
        self.assertEqual(
            risk_service.current(session_id=self.session.pk, config=CONFIG, now=1240.0),
            20,
        )

    def test_decay_never_goes_below_zero(self):
        self.add("looking_away", now=1000.0, weight=5)
        self.assertEqual(
            risk_service.current(session_id=self.session.pk, config=CONFIG, now=99000.0),
            0,
        )

    def test_decay_applies_before_the_next_addition(self):
        """
        Pasayish LAZY: keyingi qo'shishda avval eskisi kamayadi.

        Aks holda ball "muzlab" qolardi va pasayish faqat o'qishda
        ko'rinib, yozilganda yo'qolardi.
        """
        self.add("high_suspicion_phone", now=1000.0, weight=40)
        # 2 daqiqa -> 30, ustiga 20 -> 50.
        self.assertEqual(self.add("multiple_faces", now=1120.0, weight=20), 50)

    def test_score_is_capped_at_100(self):
        for index in range(10):
            self.add("high_suspicion_person", now=1000.0 + index * 100, weight=45)
        self.assertLessEqual(
            risk_service.current(session_id=self.session.pk, config=CONFIG, now=1900.0),
            100,
        )

    def test_breakdown_explains_the_score(self):
        """
        "72 ball" tekshirib bo'lmaydigan da'vo; "shundan 40 tasi
        telefon" esa tekshirib bo'ladigan.
        """
        self.add("high_suspicion_phone", now=1000.0, weight=40)
        self.add("multiple_faces", now=1000.0, weight=20)

        breakdown = risk_service.breakdown(self.session.pk)
        self.assertEqual(breakdown, {"high_suspicion_phone": 40, "multiple_faces": 20})

    def test_breakdown_does_not_decay(self):
        """
        Tarkib "nima bo'lgan" degan savolga javob beradi, "hozir
        qanchalik xavfli" degan savolga emas. Pasaytirilsa,
        apellyatsiyada "40 ball telefon uchun edi" degan da'voni
        tasdiqlab bo'lmasdi.
        """
        self.add("high_suspicion_phone", now=1000.0, weight=40)
        risk_service.current(session_id=self.session.pk, config=CONFIG, now=99000.0)
        self.assertEqual(
            risk_service.breakdown(self.session.pk), {"high_suspicion_phone": 40}
        )

    def test_zero_weight_does_not_touch_the_score(self):
        self.add("camera_reconnected", now=1000.0, weight=0)
        self.assertEqual(risk_service.breakdown(self.session.pk), {})

    def test_decay_disabled_keeps_the_score(self):
        config = {**CONFIG, "decay_per_min": 0}
        risk_service.apply(
            session_id=self.session.pk,
            event_type="looking_away",
            config=config,
            weight=5,
            now=1000.0,
        )
        self.assertEqual(
            risk_service.current(session_id=self.session.pk, config=config, now=99000.0),
            5,
        )
