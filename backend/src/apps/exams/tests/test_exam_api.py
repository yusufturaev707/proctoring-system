"""
`ExamSerializer` — platforma sarlavhasining kirish/chiqish qoidasi.

Nima uchun aynan serializer darajasida: bu maydonning butun ma'nosi
"ichkariga ochiq, tashqariga niqob" qoidasida va u faqat shu yerda
yashaydi. Model uni bilmaydi (shifrlash service'da), view esa
oddiy `ModelViewSet`.

Eng qimmat xato — PATCH bilan boshqa maydonni yangilaganda
sarlavhaning jimgina o'chib ketishi: imtihon kuni WebView 401 bilan
ochilardi va sabab hech qayerda ko'rinmasdi.
"""

from django.test import TestCase

from apps.exams import services as exam_services
from apps.exams.api.v1.serializers import ExamSerializer
from apps.exams.models import Exam

HEADER = "Authorization: Bearer Sccpeeiruieruierei3434u"


class ExamSerializerHeaderTests(TestCase):
    def test_create_stores_header_encrypted(self):
        serializer = ExamSerializer(
            data={
                "name": "Matematika",
                "site_url": "https://ntest.uzbmb.uz/login",
                "site_header": HEADER,
            }
        )
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()

        self.assertEqual(exam_services.get_site_header(exam), HEADER)
        self.assertNotIn("Sccpeeiruieruierei3434u", exam.site_header_encrypted)

    def test_response_never_contains_the_raw_header(self):
        """
        To'liq qiymat javobda BO'LMAYDI.

        Aks holda token brauzer devtools'ida, har bir ro'yxat
        so'rovida va CSV eksportida ko'rinardi - ya'ni uni
        shifrlab saqlashning ma'nosi qolmasdi.
        """
        exam = Exam.objects.create(name="Fizika")
        exam_services.set_site_header(exam, HEADER)
        exam.save(update_fields=["site_header_encrypted"])

        data = ExamSerializer(exam).data

        self.assertNotIn("site_header", data)
        self.assertIn("site_header_masked", data)
        self.assertNotIn("Sccpeeiruieruierei3434u", str(data))

    def test_patch_without_header_keeps_it(self):
        exam = Exam.objects.create(name="Kimyo")
        exam_services.set_site_header(exam, HEADER)
        exam.save(update_fields=["site_header_encrypted"])

        serializer = ExamSerializer(exam, data={"duration_minutes": 90}, partial=True)
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()

        self.assertEqual(exam_services.get_site_header(exam), HEADER)

    def test_empty_string_clears_the_header(self):
        """
        Bo'sh satr — ATAYLAB tozalash.

        "Kelmadi" holatidan (`partial` PATCH) farq qiladi: platforma
        tokensiz ishlay boshlaganda eski qiymatni bazada qoldirish
        kerak emas.
        """
        exam = Exam.objects.create(name="Biologiya")
        exam_services.set_site_header(exam, HEADER)
        exam.save(update_fields=["site_header_encrypted"])

        serializer = ExamSerializer(exam, data={"site_header": ""}, partial=True)
        serializer.is_valid(raise_exception=True)
        exam = serializer.save()

        self.assertEqual(exam.site_header_encrypted, "")

    def test_header_without_colon_is_rejected(self):
        serializer = ExamSerializer(
            data={"name": "Tarix", "site_header": "Bearer token-only"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("site_header", serializer.errors)

    def test_newline_is_rejected(self):
        """
        Ikkinchi qator — HTTP sarlavha inyeksiyasi.

        Client qiymatni so'rovga qo'yadi, ya'ni yangi qator u yerda
        ikkinchi sarlavhaga aylanib ketishi mumkin edi.
        """
        serializer = ExamSerializer(
            data={"name": "Geografiya", "site_header": "A: b\r\nX-Admin: 1"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("site_header", serializer.errors)

    def test_allowed_domains_field_is_gone(self):
        """
        Maydon butunlay olib tashlangan.

        Domen endi `site_url` dan hisoblanadi va ikkinchi manba
        (qo'lda to'ldiriladigan ro'yxat) qaytib kelmasligi kerak:
        ular ajralib ketganda imtihon oq ekranda ochilardi.
        """
        self.assertNotIn("allowed_domains", ExamSerializer().fields)
        self.assertFalse(hasattr(Exam(), "allowed_domains"))
