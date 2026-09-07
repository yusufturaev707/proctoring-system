"""
Redis Stream iste'molchisi — buferdan PostgreSQL'ga.

Bu qatlamning yagona vazifasi: **hodisa yo'qolmasligi**. Uch xil nosozlik
bor va uchalasi ham boshqacha yechim talab qiladi:

  1. Worker o'rtada yiqildi.
     `XREADGROUP` yetkazgan, lekin ACK qilinmagan yozuvlar PEL'da
     (Pending Entries List) qoladi. `>` bilan qayta o'qish ularni
     QAYTARMAYDI — u faqat yangi xabarlarni beradi. Shuning uchun har
     bir sikl avval `XAUTOCLAIM` bilan eskirgan pending yozuvlarni
     qaytarib oladi.

  2. Batch ichida bitta buzuq qator bor.
     `bulk_create` butun batchni yiqitadi. Agar shundan keyin ACK
     qilinmasa va qayta urinilsa — o'sha buzuq qator oqimni ABADIY
     to'sib qo'yadi. Shuning uchun batch yiqilsa qator-ma-qator
     yoziladi: yaxshi qatorlar o'tadi, yomoni ajratiladi.

  3. Qator umuman yozib bo'lmaydigan holatda.
     U jimgina tashlab yuborilmaydi — `:dead` oqimiga ko'chiriladi.
     Proktorlik tizimida "dalil yo'qoldi" degan holat bo'lmasligi kerak;
     hech bo'lmasa uni keyin ko'rib chiqish mumkin bo'lsin.
"""

from __future__ import annotations

import json
import logging
import os
import socket

from django.conf import settings

from apps.common.redis_client import get_redis

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "pg_writer"


def consumer_name() -> str:
    """
    Har bir worker process uchun NOYOB nom.

    Ilgari hamma "worker" nomi ostida ishlardi. `>` bilan o'qishda bu
    zarar qilmaydi, lekin PEL bitta nom ostida yig'iladi va yiqilgan
    process qaysi yozuvlarni ushlab qolganini ajratib bo'lmaydi.
    """
    return f"{socket.gethostname()}-{os.getpid()}"


def dead_letter_key(stream: str) -> str:
    return f"{stream}:dead"


def ensure_group(client, stream: str) -> None:
    try:
        client.xgroup_create(stream, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:
        # BUSYGROUP — guruh allaqachon mavjud, bu normal holat.
        if "BUSYGROUP" not in str(exc):
            raise


def _reclaim_stale(client, stream: str, count: int) -> list[tuple[str, dict]]:
    """
    Yiqilgan worker'dan qolgan pending yozuvlarni qaytarib oladi.

    `min_idle_time` flush intervalidan (5s) ANCHA katta bo'lishi kerak,
    aks holda hozir ishlayotgan boshqa worker'ning yozuvlarini tortib
    olamiz va bitta hodisa ikki marta yoziladi.
    """
    idle_ms = settings.PROCTORING["STREAM_RECLAIM_IDLE_MS"]
    try:
        result = client.xautoclaim(
            stream,
            CONSUMER_GROUP,
            consumer_name(),
            min_idle_time=idle_ms,
            start_id="0-0",
            count=count,
        )
    except Exception as exc:
        # Redis < 6.2 da `XAUTOCLAIM` yo'q — bu holatda tiklash ishlamaydi,
        # lekin asosiy oqim to'xtamasligi kerak.
        logger.warning("XAUTOCLAIM bajarilmadi (%s): %s", stream, exc)
        return []

    # Redis >= 7: [cursor, messages, deleted]; 6.2: [cursor, messages]
    messages = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else []
    entries = [(entry_id, fields) for entry_id, fields in messages if fields]

    if entries:
        logger.info(
            "%s: %s ta osilib qolgan yozuv qaytarib olindi", stream, len(entries)
        )
    return entries


def read_batch(client, stream: str, count: int) -> list[tuple[str, dict]]:
    """
    Avval osilib qolganlar, keyin yangilari.

    Tartib muhim: eski yozuvlar birinchi navbatda yozilishi kerak,
    aks holda yuklama yuqori bo'lganda ular hech qachon navbatga
    yetmasligi mumkin.
    """
    ensure_group(client, stream)

    entries = _reclaim_stale(client, stream, count)
    remaining = count - len(entries)
    if remaining <= 0:
        return entries

    try:
        response = client.xreadgroup(
            CONSUMER_GROUP, consumer_name(), {stream: ">"}, count=remaining, block=100
        )
    except Exception as exc:
        logger.error("Stream o'qishda xato (%s): %s", stream, exc)
        return entries

    if response:
        entries.extend(
            (entry_id, fields) for _, items in response for entry_id, fields in items
        )
    return entries


def ack(client, stream: str, entry_ids: list[str]) -> None:
    if not entry_ids:
        return
    try:
        client.xack(stream, CONSUMER_GROUP, *entry_ids)
    except Exception as exc:
        # ACK bajarilmasa yozuv PEL'da qoladi va keyingi siklda
        # `XAUTOCLAIM` uni qaytarib oladi — dublikat bo'ladi, lekin
        # `ignore_conflicts` uni to'sadi. Yo'qotgandan yaxshiroq.
        logger.error("XACK bajarilmadi (%s): %s", stream, exc)


def to_dead_letter(stream: str, fields: dict, reason: str) -> None:
    """
    Yozib bo'lmagan yozuvni tekshirish uchun alohida oqimga ko'chiradi.

    Bu "yo'qotmaslik"ning oxirgi qatlami. Oqim cheklangan uzunlikda —
    u to'lib qolsa Redis xotirasini yeb qo'ymasin.
    """
    try:
        get_redis().xadd(
            dead_letter_key(stream),
            {
                "reason": reason[:500],
                "payload": json.dumps(fields, default=str)[:8000],
            },
            maxlen=settings.PROCTORING["STREAM_DEAD_LETTER_MAXLEN"],
            approximate=True,
        )
    except Exception as exc:
        logger.error("Dead-letter oqimiga yozib bo'lmadi (%s): %s", stream, exc)


def write_with_fallback(model, rows: list[tuple[str, dict, object]], stream: str) -> dict:
    """
    Avval bitta `bulk_create`, yiqilsa — qator-ma-qator.

    `rows` — `(entry_id, xom_fields, model_obyekti)` uchliklari.

    Qaytaradi: `{"ok": [entry_id...], "dead": n}` — ACK qilinadigan
    yozuvlar ro'yxati va tashlab yuborilganlar soni. ACK ikkala holatda
    ham qilinadi: muvaffaqiyatli yozilgan yozuv ham, dead-letter'ga
    ko'chirilgani ham oqimni to'sib turmasligi kerak.
    """
    from django.db import transaction

    if not rows:
        return {"ok": [], "dead": 0}

    objects = [obj for _, _, obj in rows]
    try:
        with transaction.atomic():
            model.objects.bulk_create(objects, batch_size=1000, ignore_conflicts=True)
        return {"ok": [entry_id for entry_id, _, _ in rows], "dead": 0}
    except Exception as exc:
        logger.warning(
            "%s: batch yiqildi (%s ta qator), qator-ma-qator o'tilmoqda: %s",
            stream, len(objects), exc,
        )

    ok: list[str] = []
    dead = 0
    for entry_id, fields, obj in rows:
        try:
            with transaction.atomic():
                model.objects.bulk_create([obj], ignore_conflicts=True)
            ok.append(entry_id)
        except Exception as row_exc:
            logger.error("%s: qator yozilmadi, dead-letter: %s", stream, row_exc)
            to_dead_letter(stream, fields, str(row_exc))
            ok.append(entry_id)
            dead += 1

    return {"ok": ok, "dead": dead}
