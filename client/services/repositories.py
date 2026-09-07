"""
Repository qatlami - backend endpointlari shu yerda va FAQAT shu yerda.

UI hech qachon URL yozmaydi (admin panelidagi `api/endpoints.js` bilan bir
xil qoida). Endpoint yo'li o'zgarsa, o'zgarish bitta faylda qoladi.

Metodlar sinxron: ular QThread ichidan (`services/workers.py`) chaqiriladi,
UI thread'da emas.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import APP_VERSION
from core.errors import ClientError
from services import system_info
from services.api_client import ApiClient

log = logging.getLogger(__name__)


class AuthRepository:
    """Xodim autentifikatsiyasi (admin panel bilan bir xil JWT)."""

    def __init__(self, api: Optional[ApiClient] = None) -> None:
        self._api = api or ApiClient()

    def login(self, username: str, password: str) -> dict:
        return self._api.post(
            "/auth/login/",
            json_body={"username": username, "password": password},
            with_auth=False,
        )

    def me(self) -> dict:
        return self._api.get("/auth/me/")

    def logout(self, refresh: str = "") -> None:
        # Best-effort: server javob bermasa ham lokal holat tozalanadi.
        try:
            self._api.post("/auth/logout/", json_body={"refresh": refresh})
        except Exception as exc:
            log.info("Serverdan chiqishda xato (e'tiborsiz): %s", exc)


class DeviceRepository:
    """
    Mashinaning o'zi haqidagi ikkita OCHIQ endpoint (JWT talab qilmaydi):

        `/client/preflight/`  - "shu tarmoqdan kirish mumkinmi?"
        `/devices/register/`  - "bu mashinani ro'yxatga ol"

    Ikkalasi ham login'dan OLDIN chaqiriladi, shuning uchun ular bir
    joyda. Mashina haqidagi barcha ma'lumot `services/system_info.py`
    da yig'iladi: LAN IP, MAC, public IP va apparat izi. Repository
    faqat uni serverga uzatadi.
    """

    #: Preflight'da public IP ni kutish muddati (soniya).
    #:
    #: Bu YAGONA joy kutishga ruxsat berilgan: qolgan hamma joyda
    #: qiymat keshdan olinadi va bo'sh bo'lsa so'rov usiz ketaveradi.
    #: Dastur ishga tushishi bilan `prefetch()` boshlangani uchun
    #: amalda kutish deyarli bo'lmaydi.
    PUBLIC_IP_WAIT_SECONDS = 6.0

    def __init__(self, api: Optional[ApiClient] = None) -> None:
        self._api = api or ApiClient()

    # Eski nomlar saqlab qolindi - ular boshqa modullardan chaqiriladi.
    hardware_fingerprint = staticmethod(system_info.hardware_fingerprint)
    local_ip = staticmethod(system_info.local_ip)
    mac_address = staticmethod(system_info.mac_address)
    public_ip = staticmethod(system_info.public_ip)

    def preflight(self) -> dict:
        """
        Login formasini ko'rsatishdan oldingi tarmoq tekshiruvi.

        Ikki bosqich, ikkalasi ham to'sadi:

          1. LOKAL - kompyuterning tashqi manzili aniqlanadimi? Yo'q
             bo'lsa, internet yo'q degani va bu yerda to'xtaymiz. Bu
             serverdan QAT'IYROQ shart (server o'zi ko'rgan LAN manzil
             ro'yxatda bo'lsa ruxsat berardi), lekin ataylab shunday:
             imtihon tashqi platformada o'tadi, ya'ni internetsiz
             operator baribir birinchi sahifadan nariga o'tolmaydi -
             buni oqim boshida aytish halolroq.
          2. SERVER - manzil `AllowedPublicIp` ro'yxatidami.

        Public IP shu yerda KUTILADI (boshqa joylarda kutilmaydi):
        tekshiruv usiz ma'nosiz bo'lardi.
        """
        public_ip = system_info.public_ip(self.PUBLIC_IP_WAIT_SECONDS)
        if not public_ip:
            # Kod backend kodlari bilan bir xil shaklda - sahifalar
            # xatolarni faqat `code` bo'yicha ajratadi va xato qayerda
            # tug'ilgani ular uchun ahamiyatsiz.
            raise ClientError(
                "Internetga chiqish manzili aniqlanmadi.",
                code="public_ip_unknown",
            )

        try:
            return self._api.post(
                "/client/preflight/",
                json_body={"public_ip": public_ip},
                with_auth=False,
            )
        except ClientError as exc:
            # Server ikki xil rad javobini bitta kod bilan qaytaradi
            # (`ip_not_allowed`), farqi `details` da. Ularni SHU YERDA
            # ajratamiz: sahifalar faqat `code` bo'yicha qaror qabul
            # qiladi va operatorga ko'rsatiladigan matn butunlay
            # boshqacha bo'lishi kerak - biri administrator xatosi,
            # ikkinchisi kompyuterning joylashuvi haqida.
            if (exc.details or {}).get("allowlist_empty"):
                raise ClientError(
                    "Ruxsat etilgan IP'lar ro'yxati bo'sh.",
                    code="ip_allowlist_empty",
                    details=exc.details,
                    status=exc.status,
                ) from exc
            raise

    def report_access_attempt(self, *, entered_login: bool, code: str = "") -> None:
        """
        Kirish urinishini serverga xabar qiladi (`client_access.log`).

        Mashinani ANIQLAYDIGAN uchala qiymat ham yuboriladi - MAC, LAN
        IP va public IP. Har biri boshqa savolga javob beradi va
        administrator jurnalni ularning istalgani bo'yicha qidiradi:
        "shu kompyuter", "shu xona", "shu bino".

        BEST-EFFORT: bu chaqiruv oqimga ta'sir qilmaydi. Jurnalga
        yozib bo'lmagani operatorni to'xtatish uchun sabab emas -
        u allaqachon to'xtagan yoki allaqachon o'tgan.
        """
        try:
            snapshot = system_info.snapshot()
            self._api.post(
                "/client/access-attempt/",
                json_body={
                    "mac_address": snapshot["mac_address"],
                    "ip_address": snapshot["ip_address"],
                    "public_ip": snapshot["public_ip"],
                    "hostname": snapshot["info_pc"].get("hostname", ""),
                    "app_version": APP_VERSION,
                    "entered_login": bool(entered_login),
                    "code": code or "",
                },
                with_auth=False,
            )
        except Exception as exc:
            log.info("Kirish urinishini jurnalga yozib bo'lmadi (e'tiborsiz): %s", exc)

    def register(self, *, app_version: str, app_hash: str = "",
                 inventory_code: str = "") -> dict:
        """
        Uchta belgi bilan ro'yxatdan o'tish.

        Server ularni ISHONCHLILIK tartibida ishlatadi: MAC (global
        unikal) -> inventar kodi -> LAN IP + bino. Public IP esa
        binoni aniqlash uchun zaxira signal: server o'zi ko'rgan manzil
        xususiy bo'lsa (masalan server o'sha binoning ichida tursa),
        client aytgan public IP ishga tushadi.
        """
        payload = system_info.snapshot()
        payload.update(
            {
                "inventory_code": inventory_code,
                "app_version": app_version,
                "app_hash": app_hash,
            }
        )
        return self._api.post("/devices/register/", json_body=payload, with_auth=False)


class ProctoringRepository:
    """
    `/api/v1/client/...` yuzasi - imtihon oqimining butun mantig'i.

    Metodlar tartibi oqim tartibiga mos: handshake -> lookup -> face verify
    -> identity confirm -> exam access -> (heartbeat/events) -> finish.
    """

    def __init__(self, api: Optional[ApiClient] = None) -> None:
        self._api = api or ApiClient()

    # --- 1. Handshake -------------------------------------------------
    def handshake(self, *, app_version: str, app_hash: str = "",
                  monitors: int = 1, cameras: int = 1) -> dict:
        return self._api.post(
            "/client/handshake/",
            json_body={
                "app_version": app_version,
                "app_hash": app_hash,
                "hardware_fingerprint": system_info.hardware_fingerprint(),
                # Har handshake'da yangilanadi: bino rezerv kanalga
                # o'tsa, panelda eski manzil qolib ketmasligi kerak.
                "public_ip": system_info.public_ip(),
                "monitors": monitors,
                "cameras": cameras,
            },
        )

    # --- 2. Talabgorni aniqlash --------------------------------------
    def lookup_candidate(self, *, pinfl: str, exam_id: int) -> dict:
        return self._api.post(
            "/client/candidate/lookup/",
            json_body={"pinfl": pinfl, "exam_id": int(exam_id)},
        )

    # --- 3. Kirishdagi FaceID ----------------------------------------
    def verify_face(self, *, challenge: str, embedding: Optional[list] = None,
                    score: Optional[int] = None, faces_detected: int = 1,
                    image_key: str = "") -> dict:
        body: dict[str, Any] = {
            "challenge": challenge,
            "faces_detected": faces_detected,
            "image_key": image_key,
        }
        # Backend `embedding` yoki `score` dan kamida bittasini talab qiladi.
        # Etalon rasm bo'lmagan holatda (enrollment) score yo'q - shunda
        # faqat embedding yuboriladi.
        if embedding is not None:
            body["embedding"] = embedding
        if score is not None:
            body["score"] = int(score)
        return self._api.post("/client/face/verify/", json_body=body)

    # --- 4. Operator shaxsni tasdiqlaydi -----------------------------
    def confirm_identity(self, *, document_type: str, document_number: str,
                         note: str = "") -> dict:
        return self._api.post(
            "/client/identity/confirm/",
            json_body={
                "decision": "confirm",
                "document_type": document_type,
                "document_number": document_number,
                "note": note,
            },
        )

    def reject_identity(self, *, reason: str) -> dict:
        return self._api.post(
            "/client/identity/confirm/",
            json_body={"decision": "reject", "reason": reason},
        )

    # --- 5. Tashqi platformaga kirish --------------------------------
    def exam_access(self) -> dict:
        return self._api.post("/client/exam/access/")

    # --- Imtihon davomida --------------------------------------------
    def heartbeat(self, **metrics) -> dict:
        return self._api.post("/client/heartbeat/", json_body=metrics)

    def send_events(self, events: list[dict]) -> dict:
        return self._api.post("/client/events/", json_body={"events": events})

    def periodic_face(self, *, embedding: Optional[list] = None,
                      score: Optional[int] = None, faces_detected: int = 1) -> dict:
        body: dict[str, Any] = {"faces_detected": faces_detected}
        if embedding is not None:
            body["embedding"] = embedding
        if score is not None:
            body["score"] = int(score)
        return self._api.post("/client/face/periodic/", json_body=body)

    def session_state(self) -> dict:
        return self._api.get("/client/session/state/")

    # --- Skrinshotlar -------------------------------------------------
    #
    # Backend ikki xil yo'lni qo'llab-quvvatlaydi va o'rnatish profiliga
    # qarab BITTASI yoqilgan bo'ladi. Qaysi biri ekanini client sessiya
    # boshida aniqlaydi (`services/screen_capture.py`), shuning uchun
    # bu yerda uchala metod ham bor.

    def presign_screenshots(
        self, *, count: int = 1, kind: str = "screen",
        content_type: str = "image/jpeg",
    ) -> dict:
        """
        Obyekt storage'iga to'g'ridan-to'g'ri yuklash uchun URL'lar.

        Obyekt storage'i o'chirilgan bo'lsa 503 qaytadi - chaqiruvchi
        buni fayl tizimi yo'liga o'tish signali sifatida o'qiydi.
        `count` bir marta bir nechta URL olish uchun (backend chegarasi
        20 ta): har kadr uchun alohida so'rov yuborish ortiqcha yuk.
        """
        return self._api.post(
            "/client/screenshots/presign/",
            json_body={"kind": kind, "content_type": content_type, "count": int(count)},
        )

    def commit_screenshots(self, screenshots: list[dict]) -> dict:
        """
        Yuklangan skrinshotlar metadata'sini tasdiqlaydi (batch).

        Binary allaqachon storage'da; bu chaqiruv DB'ga yozuv qo'shadi.
        Backend chegarasi - bir so'rovda 50 ta.
        """
        return self._api.post(
            "/client/screenshots/commit/", json_body={"screenshots": screenshots}
        )

    def upload_screenshot(self, *, data: bytes, captured_at: str) -> dict:
        """
        Fayl tizimi yo'li: binary AYNAN shu so'rovda ketadi.

        Fayl nomi va `Content-Type` server uchun HECH NARSANI
        anglatmaydi - u faylning haqiqiy turini baytlardan aniqlaydi
        (`services/screenshots.py`), nomni esa o'zi yasaydi. Ular bu
        yerda faqat multipart shakli talab qilgani uchun berilyapti.
        """
        return self._api.request(
            "POST",
            "/client/screenshots/upload/",
            files={"file": ("screen.jpg", data, "image/jpeg")},
            data={"captured_at": captured_at},
        )

    # --- Yakunlash ----------------------------------------------------
    def finish_session(self, *, reason: str = "") -> dict:
        return self._api.post("/client/session/finish/", json_body={"reason": reason})

    def report_technical_problem(self, *, kind: str, description: str) -> dict:
        # Maydon nomi `kind` (`type` EMAS) - backend
        # `TechnicalProblemReportSerializer` bilan bir xil bo'lishi shart.
        return self._api.post(
            "/client/technical-problem/",
            json_body={"kind": kind, "description": description},
        )

    def verify_exit(self, *, password: str) -> dict:
        """
        Client'dan chiqishga ruxsat - IKKI xil parol qabul qilinadi.

        Server avval xodimning O'Z parolini (JWT bo'lsa), keyin
        viloyatning chiqish parolini sinaydi. Client bu farqni
        BILMAYDI va bilishi ham shart emas: u bitta maydon ko'rsatadi
        va javobdagi `method` ni faqat log uchun ishlatadi.

        `public_ip` yuboriladi, chunki login qilinmagan holatda
        viloyatni aniqlashning yagona yo'li shu (qurilma ro'yxatdan
        o'tgan bo'lsa, server uni `X-Device-ID` orqali ham topadi).
        """
        return self._api.post(
            "/client/exit/verify/",
            json_body={"password": password, "public_ip": system_info.public_ip()},
        )
