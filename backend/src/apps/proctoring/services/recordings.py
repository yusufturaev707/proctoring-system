"""
Mashinada qolgan yozuvlarni QAYD ETISH.

Bu yerda fayl bilan ishlanmaydi - u boshqa mashinada. Xizmat
faqat qatorni yozadi va takroriy so'rovni bitta qatorga yig'adi.

NIMA UCHUN ALOHIDA MODUL. `evidence.py` fayl bilan ishlaydi:
baytlarni tekshiradi, diskka yozadi, tartibni saqlaydi, muddat
hisoblaydi. Bu yerda ularning HECH BIRI yo'q va ikkalasini bitta
faylga qo'shish "dalil saqlash" degan tushunchani ikki xil
ma'noga bo'lardi.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import SessionNotFound
from apps.proctoring.models import ExamSession, LocalRecording

logger = logging.getLogger(__name__)


def session_without_token(*, public_id, device, now=None) -> ExamSession:
    """
    Sessiya tokeni YO'Q so'rov uchun sessiyani topadi.

    Qachon kerak: token client bilmagan holda bekor bo'lgan -
    proktor chetlashtirdi, server sessiyani o'zi yopdi yoki operator
    imtihon o'rtasida hisobdan chiqdi. Ekran yozuvi aynan shu
    paytda yakunlanadi va manzilsiz qolsa, panelda eng kerakli
    yozuv - chetlashtirilgan sessiyaniki - ko'rinmasdi.

    Token o'rnini UCHTA shart bosadi va uchalasi ham shart:

    * xodim JWT'si va `client.operate` ruxsati (view darajasida);
    * sessiya AYNAN SHU qurilmada ochilgan (`session.device`) -
      boshqa mashina birovning sessiyasiga yozuv qo'sha olmaydi;
    * yakunlangan sessiya uchun - yakundan keyin
      `RECORDING_LATE_REGISTER_SECONDS` ichida. Yakunlanmagan
      sessiya (hisobdan chiqish) cheklanmaydi: u hali tirik va
      qurilma unga baribir egalik qiladi.

    Barcha rad javoblari BITTA xato (`session_not_found`): "bunday
    sessiya bor, lekin boshqa qurilmaniki" degan javob sessiya
    identifikatorlarini sanab chiqishga yo'l ochardi.
    """
    if device is None or not public_id:
        raise SessionNotFound("Sessiya tokeni yoki identifikatori yo'q")

    session = (
        ExamSession.objects.filter(public_id=public_id, device=device)
        .only("pk", "public_id", "status", "finished_at", "device_id")
        .first()
    )
    if session is None:
        raise SessionNotFound()

    if session.status in ExamSession.TERMINAL_STATUSES:
        now = now or timezone.now()
        window = timedelta(seconds=int(settings.PROCTORING["RECORDING_LATE_REGISTER_SECONDS"]))
        if session.finished_at is None or now - session.finished_at > window:
            raise SessionNotFound("Sessiya yakunlanganiga ko'p vaqt o'tgan")

    logger.info(
        "Yozuv tokensiz qabul qilinmoqda: session=%s status=%s device=%s",
        session.pk, session.status, getattr(device, "device_id", "-"),
    )
    return session


def register(*, session, device_id: str = "", machine_mac: str = "", **data) -> LocalRecording:
    """
    Yozuvni qayd etadi (yoki mavjudini yangilaydi).

    TAKRORIY SO'ROV YANGILAYDI, ikkinchi qator yaratmaydi. Ekran
    yozuvi uchun bu ODATIY hol: client uni imtihon yakunida
    yuboradi, tarmoq xatosida esa qayta uradi - va ikkinchi
    urinishdagi hajm birinchisinikidan farq qilishi mumkin
    (fayl yopilgan). Panelda ikkita yozuv "ikkita video bor"
    bo'lib ko'rinardi.
    """
    local_path = data.pop("local_path")
    recording, created = LocalRecording.objects.update_or_create(
        session=session,
        local_path=local_path,
        defaults={
            "device_id": device_id or "",
            "machine_mac": machine_mac or "",
            **data,
        },
    )
    logger.info(
        "Mashinadagi yozuv %s: session=%s kind=%s %.1f MB path=%s",
        "qayd etildi" if created else "yangilandi",
        session.pk, recording.kind,
        recording.size_bytes / (1024 * 1024), local_path,
    )
    return recording
