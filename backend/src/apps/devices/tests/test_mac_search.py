"""
Panel qidiruvi MAC manzilni ikkala ajratgich bilan topadi
(`apps.common.filters.SearchFilter`).

Windows `getmac`/`ipconfig` `EC-D6-8A-E0-B8-93` beradi, bazada esa
`EC:D6:8A:E0:B8:93` — administrator ko'chirib qo'ygan manzil kompyuterni
topishi shart. Eski yozuvlarda `ec-d6-...` shakli ham qolgan.
"""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.common.filters import mac_term_variants
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer


class MacTermVariantsTests(SimpleTestCase):
    def test_separators_swapped(self):
        self.assertEqual(
            mac_term_variants("EC-D6-8A"), ["EC-D6-8A", "EC:D6:8A"],
        )
        self.assertEqual(mac_term_variants("d6:8a"), ["d6:8a", "d6-8a"])

    def test_bare_full_address_expanded(self):
        self.assertEqual(
            mac_term_variants("ECD68AE0B893"),
            ["ECD68AE0B893", "EC:D6:8A:E0:B8:93", "EC-D6-8A-E0-B8-93"],
        )

    def test_other_terms_untouched(self):
        # Inventar kodi, ism, qisqa o'n oltilik qism — o'zgarmaydi.
        for term in ("INV-001", "Toshkent", "ECD6", "192.168.1.5"):
            self.assertEqual(mac_term_variants(term), [term])


class ComputerMacSearchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.zone = factories.make_zone()
        user = factories.make_user(permissions=["devices.view"])
        self.auth = bearer(user)
        self.target = factories.make_computer(zone=self.zone, mac_address="EC:D6:8A:E0:B8:93")
        # Kanonik shakldan oldin yozilgan eski yozuv.
        self.legacy = factories.make_computer(zone=self.zone, mac_address="ec-d6-8a-e0-b8-94")
        self.other = factories.make_computer(zone=self.zone)

    def _search(self, term):
        response = self.client.get(
            reverse("computer-list"), {"search": term}, HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return {row["id"] for row in response.json()["data"]["results"]}

    def test_dash_and_colon_find_same_computer(self):
        for term in ("EC-D6-8A-E0-B8-93", "EC:D6:8A:E0:B8:93", "ec-d6-8a-e0-b8-93", "ECD68AE0B893"):
            with self.subTest(term=term):
                self.assertEqual(self._search(term), {self.target.pk})

    def test_partial_fragment_matches_both_forms(self):
        self.assertEqual(self._search("EC-D6-8A"), {self.target.pk, self.legacy.pk})
        self.assertEqual(self._search("E0:B8:94"), {self.legacy.pk})

    def test_non_mac_search_unchanged(self):
        self.assertEqual(self._search(self.other.inventory_code), {self.other.pk})
