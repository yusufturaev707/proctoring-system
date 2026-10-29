"""
BBA Console integratsiyasi — o'rnatish va tekshiruv.

    python manage.py bba_console fetch-ca [--out certs/bba-ca.pem]
    python manage.py bba_console check          # login + /me (huquqlar)
    python manage.py bba_console sync           # daraxt + holat (+ --inventory)
    python manage.py bba_console unblock        # login blokini keshdan olish
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.bba import services
from apps.bba.client import BbaError, ca_path, clear_login_block, fetch_ca, get_client, is_configured


class Command(BaseCommand):
    help = "BBA Console integratsiyasi: CA sertifikati, ulanish tekshiruvi, sinxronizatsiya"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["fetch-ca", "check", "sync", "unblock"])
        parser.add_argument("--out", default="", help="fetch-ca: PEM fayl yo'li (standart — BBA_CA_FILE)")
        parser.add_argument("--inventory", action="store_true", help="sync: inventory'larni ham olish")

    def handle(self, *args, action, out, inventory, **options):
        try:
            getattr(self, "_" + action.replace("-", "_"))(out=out, inventory=inventory)
        except BbaError as exc:
            raise CommandError(str(exc)) from exc

    def _fetch_ca(self, *, out, **_):
        target = Path(out) if out else ca_path()
        if target is None:
            raise CommandError("--out yoki BBA_CA_FILE kerak")
        if not target.is_absolute():
            target = settings.ROOT_DIR / target
        pem, fingerprint = fetch_ca(settings.BBA_CONSOLE["BASE_URL"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pem)
        self.stdout.write(self.style.SUCCESS(f"Saqlandi: {target}"))
        self.stdout.write(f"SHA-256: {fingerprint}")
        self.stdout.write(
            "Izni Console administratoridagi qiymat bilan solishtiring — bu yuklab olish "
            "TEKSHIRUVSIZ edi. Keyin .env: BBA_CA_FILE=" + str(out or settings.BBA_CONSOLE["CA_FILE"])
        )

    def _check(self, **_):
        if not is_configured():
            raise CommandError("BBA_ENABLED=true, BBA_USERNAME va BBA_PASSWORD kerak")
        me = get_client().me()
        user = me.get("user") or {}
        self.stdout.write(self.style.SUCCESS(
            f"Ulanish bor: {user.get('username')} (rol: {user.get('role')})"
        ))
        for grant in me.get("grants") or []:
            scope = " / ".join(filter(None, [grant.get("region_name"), grant.get("scope_name")]))
            self.stdout.write(f"  {grant.get('scope_type')}: {scope or '-'} — {', '.join(grant.get('permissions') or [])}")
        anywhere = me.get("anywhere") or {}
        if not anywhere.get("control"):
            self.stdout.write(self.style.WARNING(
                "  Diqqat: `control` huquqi yo'q — job yuborish va Wake-on-LAN Console'da rad etiladi."
            ))

    def _sync(self, *, inventory, **_):
        if not is_configured():
            raise CommandError("BBA_ENABLED=true, BBA_USERNAME va BBA_PASSWORD kerak")
        client = get_client()
        tree = services.sync_tree(client)
        result = services.sync_devices(client)
        linked = services.link_computers()
        self.stdout.write(self.style.SUCCESS(
            f"Hudud: {tree['regions']}, xona: {tree['rooms']}, kompyuter: {result['total']} "
            f"(yangi {result['created']}, o'zgargan {result['updated']}, yo'qolgan {result['missing']}); "
            f"bog'lanish o'zgardi: {linked}"
        ))
        if inventory:
            stats = services.sync_inventories(client)
            self.stdout.write(f"Inventory: olindi {stats['fetched']}, xato {stats['errors']} {stats['stopped']}")

    def _unblock(self, **_):
        clear_login_block()
        self.stdout.write(self.style.SUCCESS("Login bloki va token keshdan olindi"))
