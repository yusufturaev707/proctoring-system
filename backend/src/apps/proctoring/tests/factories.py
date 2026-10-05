"""
Test ma'lumotlari yasovchisi.

`factory_boy` qo'shilmadi: bog'liqlik zanjiri qisqa va oshkora
funksiyalar bu yerda o'qish uchun qulayroq — test o'qiyotgan odam
sessiya qanday holatda ekanini bir qarashda ko'radi.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.controls.models import Setting
from apps.devices.models import Camera, Computer, DeviceToken
from apps.exams.models import Exam, ExamSchedule
from apps.proctoring.models import ExamSession
from apps.regions.models import Region, Zone
from apps.users.models import Permission, Role, User

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def make_region(**kwargs) -> Region:
    index = _next()
    return Region.objects.create(
        **{
            "name": f"Viloyat-{index}",
            "dtm_id": index,
            "vm_number": index,
            **kwargs,
        }
    )


def make_zone(region=None, **kwargs) -> Zone:
    index = _next()
    return Zone.objects.create(
        region=region or make_region(),
        **{"name": f"Bino-{index}", "number": index, **kwargs},
    )


def make_camera(zone=None, **kwargs) -> Camera:
    index = _next()
    return Camera.objects.create(
        zone=zone or make_zone(),
        **{
            "name": f"Kamera {index}",
            "ip_address": f"10.20.0.{index % 250 + 1}",
            "mac_address": "DC:BB:CC:{:02X}:{:02X}:{:02X}".format(
                index % 256, (index // 256) % 256, (index // 65536) % 256
            ),
            **kwargs,
        },
    )


def make_computer(zone=None, **kwargs) -> Computer:
    index = _next()
    return Computer.objects.create(
        zone=zone or make_zone(),
        **{
            # Raqam ham beriladi: u bino ichida unikal va
            # `_next()` hisoblagichi buni ta'minlaydi. Bo'sh
            # qoldirish testlarni raqamsiz mashinaga bog'lab
            # qo'yardi - holbuki amalda mashinalar raqamlanadi.
            "number": index,
            "inventory_code": f"PC-{index:04d}",
            "ip_address": f"192.168.1.{index % 250 + 1}",
            "mac_address": "AA:BB:CC:{:02X}:{:02X}:{:02X}".format(
                index % 256, (index // 256) % 256, (index // 65536) % 256
            ),
            # ASOSIY identifikator - har kompyuterga o'zniki.
            "machine_uuid": machine_uuid_for(index),
            **kwargs,
        },
    )


def machine_uuid_for(index: int) -> str:
    """Testdagi kompyuter UUID'i: yaroqli (entropiyali), indeksga xos."""
    return "4C4C4544-0038-4A10-805A-{:012X}".format(0xC7C04F000000 + index)


def machine_of(device) -> dict:
    """
    Client JSHSHIR tekshiruvida yuboradigan (Machine UUID, MAC) juftligi.

    Haqiqiy client uni HAR DOIM yuboradi va `REQUIRE_MACHINE_MATCH=true`
    da server uni qurilma kompyuteri bilan solishtiradi
    (`session.require_machine_match`).
    """
    return {
        "machine_uuid": device.computer.machine_uuid,
        "mac_address": device.computer.mac_address,
    }


def make_device(computer=None, **kwargs) -> DeviceToken:
    index = _next()
    return DeviceToken.objects.create(
        computer=computer or make_computer(),
        **{
            "device_id": f"dev_test_{index}",
            "status": DeviceToken.Status.ACTIVE,
            **kwargs,
        },
    )


def make_exam(**kwargs) -> Exam:
    index = _next()
    return Exam.objects.create(**{"name": f"Imtihon-{index}", **kwargs})


def make_schedule(exam=None, zone=None, *, open_now=True, **kwargs) -> ExamSchedule:
    """Standart holatda kirish oynasi HOZIR ochiq bo'lgan jadval."""
    now = timezone.now()
    starts_at = now + timedelta(minutes=10 if open_now else 600)
    return ExamSchedule.objects.create(
        exam=exam or make_exam(),
        zone=zone,
        **{
            "exam_date": timezone.localdate(starts_at),
            "starts_at": starts_at,
            "ends_at": starts_at + timedelta(hours=3),
            "checkin_lead_minutes": 60,
            **kwargs,
        },
    )


def make_setting(**kwargs) -> Setting:
    index = _next()
    return Setting.objects.create(**{"name": f"Profil-{index}", **kwargs})


def make_user(*, permissions=None, global_role=None, **kwargs) -> User:
    """
    Berilgan ruxsat kodlari bilan xodim (rol avtomatik yaratiladi).

    `global_role` berilmasa VILOYATGA qarab tanlanadi: viloyatsiz xodim —
    respublika roli, viloyatli — viloyat roli. Ilgari viloyatsiz xodim
    `is_global` siz ham hamma narsani ko'rardi va testlar shunga
    tayangan; endi u admin panelda to'siladi (`User.lacks_region`),
    shuning uchun "hamma narsani ko'radigan xodim" rolda ochiq aytiladi.
    """
    index = _next()
    role = None
    if global_role is None:
        global_role = kwargs.get("region") is None
    if permissions is not None:
        role = Role.objects.create(name=f"Rol-{index}", key=index, is_global=global_role)
        objects = [
            Permission.objects.get_or_create(code=code, defaults={"name": code})[0]
            for code in permissions
        ]
        role.permissions.set(objects)
    return User.objects.create(
        **{"username": f"xodim{index}", "role": role, **kwargs}
    )


def make_session(*, exam=None, device=None, computer=None, **kwargs) -> ExamSession:
    index = _next()
    computer = computer or (device.computer if device else make_computer())
    return ExamSession.objects.create(
        exam=exam or make_exam(),
        device=device,
        computer=computer,
        zone=computer.zone,
        **{
            "pinfl": f"{30000000000000 + index}",
            "last_name": "Toshmatov",
            "first_name": "Ali",
            "exam_date": timezone.localdate(),
            "status": ExamSession.Status.IN_PROGRESS,
            **kwargs,
        },
    )
