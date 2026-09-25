"""
Imtihon platformasi javobining talqini.

Bu qatlam butun oqimning kirish nuqtasi: uning xulosasi talabgorni
imtihonga qo'yadi yoki qo'ymaydi. Shuning uchun testlar aynan
PLATFORMA BERGAN namuna javob ustida yozilgan — maydon nomi yoki
tur o'zgarsa (`status: true` -> `status: 1`), u shu yerda ushlanadi,
imtihon kuni emas.

Tarmoq CHAQIRILMAYDI: talqin (`_normalize`) sof funksiya va uni
so'rovsiz sinash mumkin. Retry, timeout va circuit breaker esa
`requests` va Redis xulqi — ularni bu yerda takrorlash sinovni
sekin va mo'rt qilardi.
"""

from django.test import TestCase, override_settings

from apps.common.exceptions import (
    CandidateNotEligible,
    CandidateNotFound,
    ExternalPlatformError,
)
from apps.integrations import exam_site

#: Platforma hujjatidagi namuna javob (muvaffaqiyat).
#:
#: `is_finished` ATAYLAB `1`: platformaning o'z namunasi shunday va
#: aynan shu qiymat bilan "Testga ruxsat!" qaytadi — uni to'siq deb
#: talqin qilish ruxsat berilgan talabgorni imtihonga qo'ymasdi.
SUCCESS = {
    "status": 1,
    "message": "Success",
    "data": {
        "id": 73272,
        "abitur_id": 73478,
        "imie": 32701966190024,
        "is_finished": 1,
        "image_base64": "data:image/jpeg;base64,QUJD",
        "lname": "TO‘RAYEV",
        "fname": "YUSUF",
        "mname": "JUMMA O‘G‘LI",
        "duration_time": 180,
        "test_link": "https://test.uz/login?token=-JNtDZDDcPgkdXRgQab7fBjs3Hs",
        "message": "Testga ruxsat!",
        "status": True,
    },
}

#: Javobning ESKI shakli — ismsiz va davomiyliksiz.
#:
#: Saqlanadi, chunki bu maydonlar javobga KEYIN qo'shilgan: ular yo'q
#: bo'lganda ham talqin ishlashi va talabgor imtihonga kirishi kerak.
LEGACY = {
    "status": 1,
    "message": "Success",
    "data": {
        "id": 72235,
        "abitur_id": 72441,
        "imie": 30309975270036,
        "is_finished": 1,
        "image_base64": "data:image/jpeg;base64,QUJD",
        "test_link": "https://test.uz/login?token=-JNtDZDDcPgkdXRgQab7fBjs3Hs",
        "message": "Testga ruxsat!",
        "status": True,
    },
}

NOT_FOUND = {"status": 0, "message": "Not found"}


class BuildUrlTests(TestCase):
    def test_pinfl_is_appended(self):
        self.assertEqual(
            exam_site.build_url("https://api.test.uz/check", "30309975270036"),
            "https://api.test.uz/check?imie=30309975270036",
        )

    def test_existing_query_is_kept(self):
        """
        Manzilda allaqachon parametr bo'lishi mumkin (versiya, kalit).

        Uni tashlab yuborish so'rovni jimgina buzardi va sabab
        platformaning javobida ko'rinmasdi.
        """
        url = exam_site.build_url("https://api.test.uz/check?v=2", "30309975270036")
        self.assertIn("v=2", url)
        self.assertIn("imie=30309975270036", url)

    def test_duplicate_pinfl_is_replaced(self):
        url = exam_site.build_url("https://api.test.uz/check?imie=111", "222")
        self.assertNotIn("111", url)
        self.assertEqual(url.count("imie="), 1)


class ParseHeaderTests(TestCase):
    def test_full_header(self):
        self.assertEqual(
            exam_site.parse_header("Authorization: Bearer Sccpee3434u"),
            {"Authorization": "Bearer Sccpee3434u"},
        )

    def test_value_with_colon_is_kept_whole(self):
        """Qiymat ichida ikki nuqta bo'lishi mumkin (`Basic a:b`)."""
        header = exam_site.parse_header("X-Token: id:secret")
        self.assertEqual(header, {"X-Token": "id:secret"})

    def test_empty_and_malformed_are_ignored(self):
        # Sarlavhasiz so'rov platformadan 401 oladi va sabab javobda
        # ko'rinadi — bu yerda istisno tashlash "sozlanmagan" holatni
        # "buzilgan" dan ajratmasdi.
        self.assertEqual(exam_site.parse_header(""), {})
        self.assertEqual(exam_site.parse_header("Bearer token"), {})


class NormalizeTests(TestCase):
    def test_success(self):
        result = exam_site._normalize(SUCCESS)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["external_id"], "73272")
        self.assertEqual(result["abitur_id"], "73478")
        # `imie` javobda SON bo'lib keladi — client va DB satr kutadi.
        self.assertEqual(result["pinfl"], "32701966190024")
        self.assertEqual(result["message"], "Testga ruxsat!")
        self.assertTrue(result["test_link"].startswith("https://test.uz/login"))

    def test_data_uri_prefix_is_stripped(self):
        """Client toza base64 kutadi (`PhotoView.set_image_bytes`)."""
        result = exam_site._normalize(SUCCESS)
        self.assertEqual(result["photo_base64"], "QUJD")

    def test_is_finished_does_not_block(self):
        """
        `is_finished: 1` TO'SIQ EMAS.

        Platformaning o'z namunasida u `1` bo'lgani holda
        `status: true` va "Testga ruxsat!" qaytadi — ya'ni bu maydon
        "test tugagan" degani emas. Uni to'siq deb talqin qilish
        ruxsat berilgan talabgorni imtihonga qo'ymasdi.
        """
        result = exam_site._normalize(SUCCESS)

        self.assertTrue(result["eligible"])
        self.assertTrue(result["is_finished"])

    def test_not_found(self):
        with self.assertRaises(CandidateNotFound) as ctx:
            exam_site._normalize(NOT_FOUND)
        self.assertIn("Not found", str(ctx.exception.detail))

    def test_not_allowed_uses_platform_message(self):
        """
        Ruxsat yo'q — sabab PLATFORMANIKI.

        Bizning umumiy matnimiz ("ruxsat yo'q") operatorga nima
        qilishni aytmasdi; platforma esa aniq sabab beradi.
        """
        payload = {
            "status": 1,
            "message": "Success",
            "data": {**SUCCESS["data"], "status": False, "message": "Imtihon kuni emas"},
        }
        with self.assertRaises(CandidateNotEligible) as ctx:
            exam_site._normalize(payload)
        self.assertIn("Imtihon kuni emas", str(ctx.exception.detail))

    def test_missing_test_link_is_refused_early(self):
        """
        Havolasiz ruxsat — foydasiz ruxsat.

        Buni FaceID'dan KEYIN aniqlash talabgorni butun tekshiruvdan
        o'tkazib, oxirida to'xtatardi.
        """
        payload = {
            "status": 1,
            "message": "Success",
            "data": {**SUCCESS["data"], "test_link": ""},
        }
        with self.assertRaises(CandidateNotEligible):
            exam_site._normalize(payload)

    def test_missing_data_block(self):
        with self.assertRaises(ExternalPlatformError):
            exam_site._normalize({"status": 1, "message": "Success"})

    def test_status_as_string_is_accepted(self):
        """Platformalar bir xil emas: `"1"` ham, `true` ham rost."""
        payload = {
            "status": "1",
            "message": "Success",
            "data": {**SUCCESS["data"], "status": "true"},
        }
        self.assertTrue(exam_site._normalize(payload)["eligible"])


@override_settings()
class MockModeTests(TestCase):
    def test_mock_returns_eligible_candidate(self):
        """
        `BASE_API_MOCK=true` — platformasiz to'liq oqim.

        Test muhitida shu rejim yoqilgan (`settings/test.py`), ya'ni
        sessiya testlari tashqi tarmoqqa chiqmaydi.
        """
        result = exam_site.check_candidate(
            site_url="https://api.test.uz/check", site_header="", pinfl="30309975270036"
        )

        self.assertTrue(result["eligible"])
        self.assertTrue(result["test_link"])
        # Mock'da etalon rasm YO'Q — client "enrollment" rejimiga
        # tushadi va operator hujjat bo'yicha tasdiqlaydi.
        self.assertEqual(result["photo_base64"], "")


class NameTests(TestCase):
    """
    F.I.Sh. — platforma uni `lname`/`fname`/`mname` da beradi.

    Kelgan ismni tashlab yuborish eng yomon variant bo'lardi:
    operator ekranda faqat raqamlarni ko'rib, talabgorni ism
    bo'yicha tekshira olmasdi.
    """

    def test_platform_name_fields(self):
        result = exam_site._normalize(SUCCESS)

        self.assertEqual(result["last_name"], "TO‘RAYEV")
        self.assertEqual(result["first_name"], "YUSUF")
        self.assertEqual(result["middle_name"], "JUMMA O‘G‘LI")
        # Tartib HUJJATDAGIDEK: familiya, ism, otasining ismi.
        self.assertEqual(result["full_name"], "TO‘RAYEV YUSUF JUMMA O‘G‘LI")

    def test_missing_name_is_not_an_error(self):
        """Ismsiz javob ham ishlaydi — nom o'rnida JSHSHIR turadi."""
        result = exam_site._normalize(LEGACY)

        self.assertTrue(result["eligible"])
        self.assertEqual(result["full_name"], "")

    def test_single_field_is_used_as_is(self):
        """
        `fio` bo'laklarga AJRATILMAYDI.

        To'g'ri bo'lish uchun qoida kerak, u esa har tilda boshqacha
        va xatosi ekranda darhol ko'rinardi.
        """
        payload = {**LEGACY, "data": {**LEGACY["data"], "fio": "Aliyev Vali Sobir o'g'li"}}
        result = exam_site._normalize(payload)

        self.assertEqual(result["full_name"], "Aliyev Vali Sobir o'g'li")
        self.assertEqual(result["last_name"], "")

    def test_parts_are_joined(self):
        payload = {
            **LEGACY,
            "data": {
                **LEGACY["data"],
                "last_name": "Aliyev",
                "first_name": "Vali",
                "middle_name": "Sobirovich",
            },
        }
        result = exam_site._normalize(payload)

        self.assertEqual(result["full_name"], "Aliyev Vali Sobirovich")
        self.assertEqual(result["first_name"], "Vali")

    def test_alternative_field_names(self):
        payload = {**LEGACY, "data": {**LEGACY["data"], "surname": "Aliyev", "ism": "Vali"}}
        result = exam_site._normalize(payload)

        self.assertEqual(result["full_name"], "Aliyev Vali")


class DurationTests(TestCase):
    """
    Test davomiyligi (`duration_time`, daqiqa).

    Qiymat MA'LUMOT: u imtihonni to'smaydi va client uni faqat
    ko'rsatadi. Shuning uchun buzilgan har qanday shakl 0 ga tushadi
    — bu "ma'lum emas" degani va client o'sha maydonni umuman
    ko'rsatmaydi ("0 daqiqa" yozuvi yolg'on bo'lardi).
    """

    def _with(self, value):
        return exam_site._normalize(
            {**SUCCESS, "data": {**SUCCESS["data"], "duration_time": value}}
        )

    def test_minutes_are_passed_through(self):
        self.assertEqual(exam_site._normalize(SUCCESS)["duration_minutes"], 180)

    def test_string_value_is_accepted(self):
        """Platformalar bir xil emas: `"180"` ham son bo'lib keladi."""
        self.assertEqual(self._with("180")["duration_minutes"], 180)

    def test_absent_field_is_zero(self):
        data = {
            key: value
            for key, value in SUCCESS["data"].items()
            if key != "duration_time"
        }
        result = exam_site._normalize({**SUCCESS, "data": data})
        self.assertEqual(result["duration_minutes"], 0)

    def test_broken_values_are_zero(self):
        for value in ("", None, "uch soat", -10, 0, 5000):
            with self.subTest(value=value):
                self.assertEqual(self._with(value)["duration_minutes"], 0)
