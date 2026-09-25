"""
AI kuzatuv siyosati va uning client konfiguratsiyasidagi aksi.

Eng muhim tekshiruv - `modules.objects` ning YAGONA manba ekani:
obyekt aniqlash ikki joyda yoqiladi (`Setting.is_enable_detect` va
`ProctoringPolicy.enable_objects`), lekin client'ga bitta qiymat
ketishi kerak. Aks holda "qaysi biri ustun?" degan savol client
kodida ikkinchi marta hal qilinardi va ikkalasi albatta ajralib
ketardi.
"""

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from apps.controls import services
from apps.controls.api.v1.serializers import (
    EventRiskWeightSerializer,
    ProctoringPolicySerializer,
)
from apps.controls.models import EventRiskWeight, ProctoringPolicy
from apps.proctoring.tests import factories


class ClientConfigTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_setting_without_policy_gets_safe_defaults(self):
        """
        Siyosatsiz profil `enabled=False` oladi, lekin qolgan
        qiymatlar to'liq bo'ladi.

        Bo'sh lug'at qaytarish mumkin emas: client u yerdan
        chegaralarni o'qiydi va yo'q kalitni o'z standarti bilan
        to'ldirardi - ya'ni chegara ikki joyda yashab, ajralib
        ketardi.
        """
        factories.make_setting(is_active=True)
        config = services.get_client_config()

        proctoring = config["proctoring"]
        self.assertFalse(proctoring["enabled"])
        self.assertIn("temporal", proctoring)
        self.assertEqual(proctoring["risk"]["high"], 70)

    def test_camera_check_requirement_reaches_the_client(self):
        """
        Client tekshiruvsiz boshlashni imtihon TANLASH sahifasida to'sadi.

        Usiz to'siq faqat `proctoring/start/` da chiqardi - talabgor
        FaceID va shaxs tasdig'idan o'tib bo'lgach.
        """
        setting = factories.make_setting(is_active=True)
        for required in (True, False):
            cache.clear()
            with self.settings(PROCTORING={**settings.PROCTORING, "REQUIRE_CAMERA_CHECK": required}):
                self.assertIs(
                    services.get_client_config()["proctoring"]["camera"]["check_required"], required
                )
        ProctoringPolicy.objects.create(setting=setting, is_enabled=True)
        cache.clear()
        self.assertIn("check_required", services.get_client_config()["proctoring"]["camera"])

    def test_objects_module_needs_both_flags(self):
        setting = factories.make_setting(is_active=True, is_enable_detect=False)
        ProctoringPolicy.objects.create(setting=setting, is_enabled=True, enable_objects=True)

        self.assertFalse(services.get_client_config()["proctoring"]["modules"]["objects"])

        cache.clear()
        setting.is_enable_detect = True
        setting.save()
        self.assertTrue(services.get_client_config()["proctoring"]["modules"]["objects"])

    def test_policy_save_invalidates_setting_cache(self):
        """
        Siyosat `Setting` kalitida keshlanadi.

        Tozalanmasa administrator panelda qiymatni o'zgartirib, 5
        daqiqa davomida hech narsa o'zgarmaganini ko'radi va buni
        xato deb hisoblab yana o'zgartiradi.
        """
        setting = factories.make_setting(is_active=True)
        policy = ProctoringPolicy.objects.create(setting=setting, is_enabled=False)
        self.assertFalse(services.get_client_config()["proctoring"]["enabled"])

        policy.is_enabled = True
        policy.save()
        self.assertTrue(services.get_client_config()["proctoring"]["enabled"])

    def test_policy_delete_invalidates_setting_cache(self):
        """
        Siyosat o'chirilganda profil standart qiymatlarga QAYTADI.

        Kesh tozalanmasa, client 5 daqiqa davomida allaqachon YO'Q
        siyosat bo'yicha ishlardi — masalan "ikkinchi kamera
        majburiy" talabi olib tashlangan bo'lsa ham imtihonni
        bloklab turaverardi.
        """
        setting = factories.make_setting(is_active=True)
        policy = ProctoringPolicy.objects.create(
            setting=setting, is_enabled=True, camera_count=2
        )
        # Keshga tushirib olamiz.
        self.assertTrue(services.get_client_config()["proctoring"]["enabled"])

        policy.delete()

        proctoring = services.get_client_config()["proctoring"]
        self.assertFalse(proctoring["enabled"])
        self.assertEqual(proctoring["camera"]["count"], 1)

    def test_attached_setting_wins_over_global(self):
        """
        Imtihonga biriktirilgan profil global standartdan USTUN.

        Bu butun `Setting` modelining mavjudlik sababi va u uchta
        bo'g'inli zanjir: `Exam.setting` -> `Setting.proctoring` ->
        `get_client_config(exam)`. Zanjirning bitta bo'g'ini uzilsa
        (masalan `_with_relations` da `proctoring` unutilsa), xato
        JIMGINA yuz beradi: client global qiymat bilan ishlaydi,
        server esa imtihonnikini kutadi.
        """
        exam_setting = factories.make_setting()
        ProctoringPolicy.objects.create(
            setting=exam_setting, is_enabled=True, camera_count=2,
            secondary_required=True, min_fps=25,
        )
        exam = factories.make_exam(setting=exam_setting)
        # Global standart — siyosatsiz.
        factories.make_setting(is_active=True)

        self.assertFalse(services.get_client_config()["proctoring"]["enabled"])

        proctoring = services.get_client_config(exam)["proctoring"]
        self.assertTrue(proctoring["enabled"])
        self.assertEqual(proctoring["camera"]["count"], 2)
        self.assertTrue(proctoring["camera"]["secondary_required"])
        self.assertEqual(proctoring["camera"]["min_fps"], 25)

    def test_detection_classes_carry_risk_weight(self):
        from apps.controls.models import CocoObject

        setting = factories.make_setting(is_active=True, is_enable_detect=True)
        phone = CocoObject.objects.create(name="cell phone", code=67, risk_weight=40)
        setting.detect_classes.set([phone])

        classes = services.get_client_config()["detection"]["classes"]
        self.assertEqual(classes[0]["risk_weight"], 40)


class PolicyValidationTests(TestCase):
    def setUp(self):
        self.setting = factories.make_setting()

    def test_thresholds_must_increase(self):
        serializer = ProctoringPolicySerializer(
            data={
                "setting": self.setting.pk,
                "threshold_low": 50,
                "threshold_medium": 30,
                "threshold_high": 70,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("threshold_medium", serializer.errors)

    def test_single_camera_cannot_require_secondary(self):
        """
        Bu kombinatsiya imtihonni HECH QACHON boshlanmaydigan qiladi.

        Uni faqat imtihon kuni, talabgor mashina oldida o'tirganda
        sezish mumkin - shuning uchun panel darajasida to'siladi.
        """
        serializer = ProctoringPolicySerializer(
            data={
                "setting": self.setting.pk,
                "camera_count": 1,
                "secondary_required": True,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("secondary_required", serializer.errors)

    def test_policy_cannot_move_to_another_setting(self):
        policy = ProctoringPolicy.objects.create(setting=self.setting)
        other = factories.make_setting()

        serializer = ProctoringPolicySerializer(
            policy, data={"setting": other.pk}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("setting", serializer.errors)


class RiskWeightTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_unknown_event_type_is_rejected(self):
        """
        Noma'lum tur jimgina yozilib, hech qachon ishlamasdi.

        Administrator uni panelda ko'rib turardi va ball nima uchun
        o'zgarmayotganini tushunolmasdi.
        """
        serializer = EventRiskWeightSerializer(
            data={"event_type": "telepatiya_aniqlandi", "weight": 50}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("event_type", serializer.errors)

    def test_known_event_type_is_accepted(self):
        serializer = EventRiskWeightSerializer(
            data={"event_type": "high_suspicion_phone", "weight": 55, "cooldown_s": 20}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_cooldown_is_capped(self):
        """
        Cooldown haqiqatan ishlaydi, ya'ni ~9 soatlik qiymat shu turni
        butun imtihon davomida ballga faqat bir marta qo'shardi.
        """
        serializer = EventRiskWeightSerializer(
            data={"event_type": "looking_away", "weight": 5, "cooldown_s": 3601}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("cooldown_s", serializer.errors)

    def test_severity_is_not_part_of_the_api(self):
        """
        Jiddiylikni client beradi; panel undan qiymat qabul qilsa,
        administrator ishlamaydigan sozlamani o'zgartirib yurardi.
        """
        self.assertNotIn("severity", EventRiskWeightSerializer().fields)

    def test_cooldown_map_skips_zero(self):
        """
        `0` - "siyosatdagi qiymat", "cooldown yo'q" EMAS. Lug'atga
        tushsa, faqat og'irligi uchun yaratilgan qator shu turni
        cooldown'siz qoldirardi.
        """
        EventRiskWeight.objects.create(event_type="looking_away", weight=3, cooldown_s=180)
        EventRiskWeight.objects.create(event_type="window_blur", weight=2, cooldown_s=0)
        EventRiskWeight.objects.create(
            event_type="eyes_closed", weight=2, cooldown_s=90, is_active=False
        )

        self.assertEqual(services.risk_cooldown_map(), {"looking_away": 180})

    def test_empty_table_returns_empty_map(self):
        """
        Bo'sh jadval - "og'irlik yo'q" degani EMAS.

        Chaqiruvchi kod bo'sh lug'atni ko'rib, o'zidagi zaxira
        qiymatlarga tushadi (`ingest.RISK_WEIGHTS`). "Sozlanmagan
        tizim ballni umuman hisoblamaydi" holati chetlashtirish
        qarorini asossiz qoldirardi.
        """
        self.assertEqual(services.risk_weight_map(), {})

    def test_active_rows_are_cached_and_invalidated(self):
        EventRiskWeight.objects.create(event_type="looking_away", weight=7)
        self.assertEqual(services.risk_weight_map()["looking_away"], 7)

        EventRiskWeight.objects.filter(event_type="looking_away").update(weight=99)
        # Kesh hali eski qiymatni beradi - bu kutilgan xulq.
        self.assertEqual(services.risk_weight_map()["looking_away"], 7)

        services.invalidate_risk_weight_cache()
        self.assertEqual(services.risk_weight_map()["looking_away"], 99)

    def test_inactive_rows_are_excluded(self):
        EventRiskWeight.objects.create(event_type="eyes_closed", weight=5, is_active=False)
        self.assertNotIn("eyes_closed", services.risk_weight_map())
