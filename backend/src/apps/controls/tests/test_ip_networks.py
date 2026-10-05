"""
Ruxsat ro'yxatida TARMOQ (CIDR), binoga bog'langan.

Uch topologiya bitta mexanizmda:

  * viloyat binosi internet orqali — bitta tashqi (NAT) IP (avvalgidek);
  * server joylashgan bino — server clientlarni LAN manzili bilan ko'radi;
  * kelajakdagi VPN — har bino o'z subnet'i bilan.

`ALLOW_PRIVATE_SOURCE_IP` istalgan xususiy manzilni binoga bog'lamasdan
o'tkazardi; tarmoq yozuvi esa faqat o'sha tarmoqni va faqat o'sha binoni
ochadi. Testlarda sozlama `false` (`settings/test.py`).
"""

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.controls import services
from apps.controls.models import AllowedPublicIp
from apps.devices.services import resolve_zone_by_public_ip
from apps.proctoring.tests import factories
from apps.proctoring.tests.test_client_api import bearer

HQ_NETWORK = "192.168.0.0/24"


class _CacheCleared(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


class CleanAllowlistEntryTests(_CacheCleared):
    def test_exactly_one_of_ip_or_network(self):
        for kwargs in ({}, {"ip_address": "8.8.8.8", "network": HQ_NETWORK}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                services.clean_allowlist_entry(**kwargs)

    def test_network_is_canonicalised(self):
        self.assertEqual(
            services.clean_allowlist_entry(network=" 192.168.0.15/24 "), (None, HQ_NETWORK)
        )

    def test_ip_entry_is_returned_as_is(self):
        self.assertEqual(services.clean_allowlist_entry(ip_address="8.8.8.8"), ("8.8.8.8", ""))

    def test_invalid_single_host_and_too_wide_networks_are_rejected(self):
        for value in ("192.168.0.0/33", "not-a-network", "192.168.0.10/32", "10.0.0.0/7"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                services.clean_allowlist_entry(network=value)

    def test_overlapping_networks_are_rejected(self):
        """Bitta manzil ikki binoga tegishli bo'lib qolmasin."""
        AllowedPublicIp.objects.create(network=HQ_NETWORK, zone=factories.make_zone())
        for value in ("192.168.0.128/25", "192.168.0.0/16", HQ_NETWORK):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                services.clean_allowlist_entry(network=value)

    def test_editing_a_network_does_not_overlap_itself(self):
        row = AllowedPublicIp.objects.create(network=HQ_NETWORK)
        self.assertEqual(
            services.clean_allowlist_entry(network=HQ_NETWORK, exclude_pk=row.pk),
            (None, HQ_NETWORK),
        )

    def test_database_enforces_one_kind(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            AllowedPublicIp.objects.create(ip_address=None, network="")


class NetworkAllowlistTests(_CacheCleared):
    def setUp(self):
        super().setUp()
        self.hq = factories.make_zone()
        self.other = factories.make_zone()
        AllowedPublicIp.objects.create(network=HQ_NETWORK, zone=self.hq)

    def test_address_inside_network_is_allowed_for_its_building_only(self):
        self.assertTrue(services.is_ip_allowed("192.168.0.168", self.hq.pk))
        self.assertFalse(services.is_ip_allowed("192.168.0.168", self.other.pk))

    def test_address_outside_network_is_refused(self):
        """Ofisning boshqa ichki tarmog'i — `ALLOW_PRIVATE_SOURCE_IP` dan farqi shu."""
        self.assertFalse(services.is_ip_allowed("192.168.1.5", self.hq.pk))
        self.assertFalse(services.is_ip_allowed("10.0.0.5", self.hq.pk))

    def test_internet_buildings_keep_working(self):
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.other)
        services.invalidate_ip_cache()

        self.assertTrue(services.is_ip_allowed("8.8.8.8", self.other.pk))
        self.assertFalse(services.is_ip_allowed("8.8.8.8", self.hq.pk))

    def test_exact_ip_wins_over_network(self):
        AllowedPublicIp.objects.create(ip_address="192.168.0.50", zone=self.other)
        services.invalidate_ip_cache()

        self.assertTrue(services.is_ip_allowed("192.168.0.50", self.other.pk))
        self.assertFalse(services.is_ip_allowed("192.168.0.50", self.hq.pk))

    def test_global_network_allows_every_building(self):
        AllowedPublicIp.objects.create(network="10.20.0.0/16")
        services.invalidate_ip_cache()

        self.assertTrue(services.is_ip_allowed("10.20.3.4", self.other.pk))

    def test_inactive_network_is_ignored(self):
        AllowedPublicIp.objects.filter(network=HQ_NETWORK).update(is_active=False)
        AllowedPublicIp.objects.create(ip_address="8.8.8.8")
        services.invalidate_ip_cache()

        self.assertFalse(services.is_ip_allowed("192.168.0.168", self.hq.pk))

    def test_list_with_only_networks_is_not_empty(self):
        """Faqat tarmoq bo'lsa ham ro'yxat to'ldirilgan — tekshiruv kuchda."""
        self.assertFalse(services.allowlist_empty())
        self.assertTrue(services.ip_check_enforced())

    def test_building_is_resolved_from_network(self):
        """Qurilmani ro'yxatga olishda bino (VPN'da tashqi IP yo'q)."""
        self.assertEqual(resolve_zone_by_public_ip("192.168.0.20"), self.hq)
        self.assertIsNone(resolve_zone_by_public_ip("192.168.1.20"))

    def test_global_network_does_not_resolve_a_building(self):
        AllowedPublicIp.objects.create(network="10.20.0.0/16")
        services.invalidate_ip_cache()

        self.assertIsNone(resolve_zone_by_public_ip("10.20.3.4"))


class NetworkPreflightTests(_CacheCleared):
    def setUp(self):
        super().setUp()
        self.hq = factories.make_zone()
        AllowedPublicIp.objects.create(network=HQ_NETWORK, zone=self.hq)

    def test_observed_lan_address_passes_without_public_ip_in_list(self):
        """VPN/LAN: binoning tashqi IP'si ro'yxatda bo'lmasa ham login formasi ochiladi."""
        result = services.network_preflight(public_ip="84.54.0.1", observed_ip="192.168.0.168")

        self.assertTrue(result["allowed"])
        self.assertEqual(result["zone"]["id"], self.hq.pk)

    def test_unknown_addresses_are_refused(self):
        result = services.network_preflight(public_ip="84.54.0.1", observed_ip="192.168.7.7")

        self.assertFalse(result["allowed"])
        self.assertIsNone(result["zone"])

    def test_public_ip_still_decides_for_internet_buildings(self):
        other = factories.make_zone()
        AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=other)
        services.invalidate_ip_cache()

        result = services.network_preflight(public_ip="8.8.8.8", observed_ip="8.8.8.8")

        self.assertTrue(result["allowed"])
        self.assertEqual(result["zone"]["id"], other.pk)


class AllowedIpApiTests(_CacheCleared):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.zone = factories.make_zone()
        self.auth = bearer(
            factories.make_user(permissions=["controls.ip_manage", "controls.ip_view"])
        )
        self.url = reverse("allowed-ip-list")

    def create(self, **payload):
        return self.client.post(
            self.url, {"zone": self.zone.pk, **payload}, format="json", HTTP_AUTHORIZATION=self.auth
        )

    def test_network_entry_is_created_canonical_and_effective_immediately(self):
        response = self.create(network="192.168.0.77/24", name="Bosh bino LAN")

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["network"], HQ_NETWORK)
        self.assertIsNone(data["ip_address"])
        # Kesh tozalangan — 5 daqiqa kutilmaydi.
        self.assertTrue(services.is_ip_allowed("192.168.0.168", self.zone.pk))

    def test_both_or_neither_is_rejected(self):
        for payload in ({}, {"ip_address": "8.8.8.8", "network": HQ_NETWORK}):
            with self.subTest(payload=payload):
                response = self.create(**payload)
                self.assertEqual(response.status_code, 400, response.content)

    def test_overlapping_network_is_rejected(self):
        self.assertEqual(self.create(network=HQ_NETWORK).status_code, 201)

        response = self.create(network="192.168.0.0/25")

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("network", response.json()["error"]["details"])

    def test_ip_entry_can_be_switched_to_network(self):
        row = AllowedPublicIp.objects.create(ip_address="8.8.8.8", zone=self.zone)

        response = self.client.patch(
            reverse("allowed-ip-detail", args=[row.pk]),
            {"ip_address": "", "network": HQ_NETWORK},
            format="json",
            HTTP_AUTHORIZATION=self.auth,
        )

        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertIsNone(row.ip_address)
        self.assertEqual(row.network, HQ_NETWORK)

    def test_ip_entries_are_unaffected(self):
        response = self.create(ip_address="8.8.4.4")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["network"], "")

    def test_duplicate_ip_is_still_rejected(self):
        self.assertEqual(self.create(ip_address="8.8.4.4").status_code, 201)

        response = self.create(ip_address="8.8.4.4")

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("ip_address", response.json()["error"]["details"])


class HandshakeFromBuildingNetworkTests(_CacheCleared):
    """Server joylashgan bino: client LAN manzili bilan keladi."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.hq = factories.make_zone()
        AllowedPublicIp.objects.create(network=HQ_NETWORK, zone=self.hq)
        self.user = factories.make_user(permissions=["client.operate"])

    def handshake(self, device, source_ip):
        return self.client.post(
            reverse("client-handshake"),
            {"app_version": "1.0.0", **factories.machine_of(device)},
            format="json",
            HTTP_AUTHORIZATION=bearer(self.user),
            HTTP_X_DEVICE_ID=device.device_id,
            REMOTE_ADDR=source_ip,
        )

    def test_lan_client_of_this_building_passes(self):
        device = factories.make_device(computer=factories.make_computer(zone=self.hq))

        response = self.handshake(device, "192.168.0.168")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["data"]["machine"]["allowed"])

    def test_other_lan_and_other_building_are_refused(self):
        hq_device = factories.make_device(computer=factories.make_computer(zone=self.hq))
        other_device = factories.make_device(computer=factories.make_computer())

        for device, source_ip in ((hq_device, "192.168.1.5"), (other_device, "192.168.0.168")):
            with self.subTest(source_ip=source_ip):
                response = self.handshake(device, source_ip)
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(response.json()["error"]["code"], "ip_not_allowed")
