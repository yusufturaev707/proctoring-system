"""
Repository qatlami - backend endpointlari shu yerda va FAQAT shu yerda.

UI hech qachon URL yozmaydi (admin panelidagi `api/endpoints.js` bilan bir
xil qoida). Endpoint yo'li o'zgarsa, o'zgarish bitta faylda qoladi.

Metodlar sinxron: ular QThread ichidan (`services/workers.py`) chaqiriladi,
UI thread'da emas.
"""

from __future__ import annotations

import json
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

    def logout(self, refresh: str = "", *, access: str = "") -> None:
        # Best-effort: server javob bermasa ham lokal holat tozalanadi.
        # `access` — chiqish FON thread'ida ketadi va shu paytda lokal
        # tokenlar allaqachon tozalangan bo'ladi (`AuthService.logout`).
        # Qisqa timeout, takrorsiz: chiqishni hech kim kutmaydi.
        try:
            self._api.post(
                "/auth/logout/", json_body={"refresh": refresh},
                auth_token=access or None, timeout=5.0, retries=0,
            )
        except Exception as exc:
            log.info("Serverdan chiqishda xato (e'tiborsiz): %s", type(exc).__name__)


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
                # Faqat o'qiydi ("ro'yxatdami?") — takrorlash xavfsiz.
                idempotent=True,
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

        Mashinani ANIQLAYDIGAN qiymatlar yuboriladi - Machine UUID, MAC,
        LAN IP va public IP. Har biri boshqa savolga javob beradi va
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
                    "machine_uuid": snapshot["machine_uuid"],
                    "mac_address": snapshot["mac_address"],
                    "ip_address": snapshot["ip_address"],
                    "public_ip": snapshot["public_ip"],
                    "hostname": snapshot["info_pc"].get("hostname", ""),
                    "app_version": APP_VERSION,
                    "entered_login": bool(entered_login),
                    "code": code or "",
                },
                with_auth=False,
                retries=0,
            )
        except Exception as exc:
            log.info("Kirish urinishini jurnalga yozib bo'lmadi (e'tiborsiz): %s", exc)

    def register(self, *, app_version: str, app_hash: str = "",
                 inventory_code: str = "") -> dict:
        """
        To'rtta belgi bilan ro'yxatdan o'tish.

        Server ularni ISHONCHLILIK tartibida ishlatadi: Machine UUID (ona
        plata) -> MAC (UUID'siz eski yozuvlar) -> inventar kodi -> LAN
        IP + bino. Public IP esa
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


def _face_files(image, reference_image) -> dict:
    """
    FaceID so'rovining fayl qismini yig'adi.

    IKKALA RASM IXTIYORIY va mustaqil: kamera kadrni bermagan
    bo'lishi ham, platforma hujjat rasmini bermagan bo'lishi ham
    mumkin. Bo'sh maydonni yuborish serverda "buzilgan fayl" bo'lib
    ko'rinardi, shuning uchun yo'q rasm umuman qo'shilmaydi.
    """
    files = {}
    if image:
        files["image"] = ("face.jpg", image, "image/jpeg")
    if reference_image:
        files["reference_image"] = ("passport.jpg", reference_image, "image/jpeg")
    return files


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
                  monitors: int = 1, cameras: int = 1,
                  hardware: Optional[dict] = None,
                  machine: Optional[dict] = None) -> dict:
        """
        Qurilma holati va bugungi imtihonlar.

        `machine` — `system_info.machine_identity()` natijasi
        (`machine_uuid`, `mac`, `ip`). Server UUID ni
        `Computer.machine_uuid` bilan SOLISHTIRADI va javobda
        `machine.allowed` qaytaradi; MAC - ikkilamchi (UUID'siz eski
        yozuvni bir marta bog'lash va apparat izi formatining o'tishi).
        Qiymat yuborilmasa tekshiruv "noma'lum" bo'lib qoladi va
        server sozlamasiga qarab u ham to'siq bo'lishi mumkin -
        shuning uchun uni yuborish IXTIYORIY emas, majburiy
        amaliyot (chaqiruvchi `AuthService.handshake`).

        `hardware` — `proctoring.hardware.report()` natijasi
        (`gpu_name`, `performance_profile`, `detail`). IXTIYORIY va
        bu ongli: apparat aniqlash fon thread'ida ketadi va
        handshake uni KUTMAYDI. Bo'sh kelsa server tegishli
        maydonlarga tegmaydi — eski qiymat saqlanib qoladi, ya'ni
        bir marta aniqlangan mashina keyingi sekin ishga tushishda
        "GPU yo'q" bo'lib qolmaydi.
        """
        hardware = hardware or {}
        machine = machine or {}
        body = {
            "app_version": app_version,
            "app_hash": app_hash,
            "hardware_fingerprint": system_info.hardware_fingerprint(),
            # Har handshake'da yangilanadi: bino rezerv kanalga
            # o'tsa, panelda eski manzil qolib ketmasligi kerak.
            "public_ip": system_info.public_ip(),
            "monitors": monitors,
            "cameras": cameras,
        }
        # UUID HAR DOIM yuboriladi (u hech qachon bo'sh emas va keshda):
        # usiz server eski MAC qoidasiga tushardi.
        body["machine_uuid"] = machine.get("machine_uuid") or system_info.machine_uuid()
        if machine.get("mac"):
            body["mac_address"] = machine["mac"]
        if machine.get("ip"):
            body["ip_address"] = machine["ip"]
        if hardware:
            body["gpu_name"] = hardware.get("gpu_name", "")
            body["performance_profile"] = hardware.get("performance_profile", "")
            # Tafsilot (CPU, RAM, VRAM, provayderlar, GPU
            # ogohlantirishi) `Computer.info_pc` ga tushadi:
            # qurilma yozuvida faqat IKKI qidiriladigan qiymat
            # bor, "nega sekin?" degan savolga esa aynan shu
            # tafsilot javob beradi.
            body["info_pc"] = {
                **system_info.info_pc(),
                "hardware": hardware.get("detail") or {},
            }
        # IDEMPOTENT: qurilma ma'lumotini yangilaydi, UUID'ni faqat
        # bir marta bog'laydi — takroriy so'rov natijani o'zgartirmaydi.
        return self._api.post("/client/handshake/", json_body=body, idempotent=True)

    # --- 1b. Kamera ---------------------------------------------------
    def presence(self, *, in_exam: bool = False) -> dict:
        """
        "Client ishlab turibdi" signali (sessiyasiz ham).

        NIMA UCHUN HEARTBEAT YETMAYDI: u faqat imtihon davomida
        yuboriladi, mashina esa kunning katta qismini talabgor
        kutib o'tkazadi. Signalsiz server 120 soniyadan keyin
        mashinani "offline" deb belgilaydi va panelda ishlab
        turgan kompyuter o'chirilgandek ko'rinadi.
        """
        # `retries=0`: davriy signal — keyingisi baribir keladi; so'rov
        # ichida takrorlash uzilishda serverga ortiqcha yuk bo'lardi.
        return self._api.post(
            "/client/presence/", json_body={"in_exam": bool(in_exam)}, retries=0
        )

    def camera_config(self, *, exam_id: Optional[int] = None) -> dict:
        """
        Binodagi kameralar ro'yxati va kuzatuv siyosati.

        ROLLAR JAVOBDA YO'Q: ularni operator client tomonda tanlaydi
        (`proctoring/camera/roles.py`). Server faqat kompyuter turgan
        binodagi faol IP kameralarni beradi - kredensial ularning
        har biri uchun alohida so'raladi.

        `exam_id` IXTIYORIY va bu bo'shliq ongli: kamera tekshiruvi
        login'dan keyin, imtihon tanlashdan OLDIN o'tadi - o'sha
        paytda qaysi imtihon bo'lishi hali ma'lum emas. Berilmasa
        global siyosat qaytadi, imtihonniki esa boshlash paytida
        server tomonidan qayta tekshiriladi.
        """
        params = {"exam": int(exam_id)} if exam_id else None
        return self._api.get("/client/camera/config/", params=params)

    def camera_stream(self, *, camera_id: int, role: str = "primary") -> dict:
        """
        IP kamera uchun RTSP manzili (kredensial bilan).

        SO'ROV KAMERA ID BO'YICHA. Ilgari u ROL bo'yicha ketardi va
        server javobni `CameraAssignment` jadvalidan izlardi;
        biriktirish olib tashlangach rolni faqat client biladi.
        `role` esa yuboriladi, lekin faqat AUDIT uchun: jurnalda
        "qaysi vazifa uchun so'raldi" degan yozuv qolishi kerak.

        NATIJANI SAQLAMANG. U parol o'z ichiga oladi va uni
        `AppState` ga, faylga yoki log'ga yozish kredensialni
        mashinada qoldirish demak. `CameraManager` uni oqim
        ochilayotgan paytda so'raydi va o'sha zahoti ishlatib
        yuboradi - shuning uchun u manzilni SATR emas, FUNKSIYA
        ko'rinishida qabul qiladi.
        """
        # Zaxira slot (`spare:<kalit>`) - server uchun "preview": u rolni
        # faqat audit uchun yozadi va boshqa qiymatni qabul qilmaydi.
        role = role if role in ("primary", "secondary") else "preview"
        return self._api.post(
            "/client/camera/stream/",
            json_body={"camera_id": int(camera_id), "role": role},
            # Takror audit'da dublikat bermaydi (`CAMERA_STREAM_GRANT_TTL`).
            idempotent=True,
        )

    def exam_config(self, *, exam_id: int) -> dict:
        """
        Tanlangan imtihonning TO'LIQ client profili.

        Handshake global standartni beradi (u imtihon tanlashdan
        oldin bajariladi), bu esa aynan shu imtihonnikini. Farq
        haqiqiy: `Exam.setting` biriktirilgan bo'lsa, FaceID
        chegarasi, skrinshot oralig'i va bloklanadigan tugmalar
        boshqacha bo'ladi.
        """
        return self._api.get("/client/exam/config/", params={"exam": int(exam_id)})

    def camera_check(self, *, cameras: list, exam_id=None) -> dict:
        """
        Kamera tekshiruvi: XOM O'LCHOVLARNI yuboradi.

        Client bu yerda hech qanday xulosa yubormaydi ("ok", "passed"
        kabi maydonlar serializerda ham qabul qilinmaydi): baholashni
        server bajaradi. Client aytgan xulosaga ishonish
        o'zgartirilgan nusxaga eshikni ochib qo'yardi.
        """
        payload: dict = {"cameras": cameras}
        if exam_id:
            payload["exam_id"] = int(exam_id)
        # O'lchov snapshot'i ustiga yoziladi — takror xavfsiz.
        return self._api.post("/client/camera/check/", json_body=payload, idempotent=True)

    def proctoring_start(self, *, ai_profile: str = "") -> dict:
        """
        Kuzatuvni ishga tushiradi — "START EXAM" nuqtasi.

        WebView ochilishidan OLDIN chaqiriladi. Server bu yerda
        kamera tekshiruvini majburlaydi: `camera_check_required`
        (tekshiruv yo'q/eskirgan) yoki `camera_check_failed`
        (tekshiruv bor, lekin talablarga mos emas).
        """
        return self._api.post(
            "/client/proctoring/start/", json_body={"ai_profile": ai_profile}
        )

    def proctoring_stop(self, *, reason: str = "") -> dict:
        return self._api.post(
            "/client/proctoring/stop/", json_body={"reason": reason}, retries=0
        )

    # --- 2. Talabgorni aniqlash --------------------------------------
    def lookup_candidate(self, *, pinfl: str, exam_id: int, mac_address: str = "",
                         machine_uuid: str = "") -> dict:
        body = {
            "pinfl": pinfl,
            "exam_id": int(exam_id),
            # Jismoniy mashina — server uni kompyuter broni bilan
            # solishtiradi ("talabgor AYNAN shu stoldami?"). Asos -
            # Machine UUID (keshdan, fon thread'ida bloklamaydi).
            "machine_uuid": machine_uuid or system_info.machine_uuid(),
        }
        # MAC - ikkilamchi: UUID'si hali yozilmagan eski kompyuter
        # yozuvlari uchun. Bo'sh bo'lsa yuborilmaydi.
        if mac_address:
            body["mac_address"] = mac_address
        return self._api.post("/client/candidate/lookup/", json_body=body)

    # --- 3. Kirishdagi FaceID ----------------------------------------
    def verify_face(self, *, challenge: str, embedding: Optional[list] = None,
                    score: Optional[int] = None, faces_detected: int = 1,
                    image: Optional[bytes] = None, reference_image: Optional[bytes] = None,
                    image_key: str = "") -> dict:
        """
        Moslik TASDIQLANGAN — sessiya ochiladi.

        Solishtirishni client bajardi; bu yerda uning natijasi ketadi:
        etalon vektor (server uni sessiyaga muzlatadi), ball va o'sha
        paytdagi JONLI KADR.

        RASM BOR BO'LSA `multipart/form-data`. Vektor o'shanda JSON
        SATR sifatida ketadi: form-data ichma-ich strukturani
        ko'tarmaydi (dalildagi `boxes` bilan bir xil qoida).
        Rasmsiz holatda oddiy JSON yuboriladi - server ikkalasini
        ham qabul qiladi.
        """
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

        if not image and not reference_image:
            return self._api.post("/client/face/verify/", json_body=body)

        if embedding is not None:
            body["embedding"] = json.dumps(embedding)
        return self._api.request(
            "POST",
            "/client/face/verify/",
            files=_face_files(image, reference_image),
            data=body,
        )

    def face_attempt(self, *, challenge: str, score: Optional[int] = None,
                     faces_detected: int = 1, image: Optional[bytes] = None,
                     reference_image: Optional[bytes] = None) -> dict:
        """
        Kirishda MOS KELMAGAN urinish: rasm va ball.

        Sessiya YARATILMAYDI va `challenge` sarflanmaydi - talabgor
        qayta urinib ko'radi. Yozuv esa qoladi: kadrda boshqa odam
        turgan bo'lishi mumkin.

        Vektor YUBORILMAYDI: u faqat sessiya etaloni sifatida
        ma'noga ega, sessiya esa ochilmadi.

        Qaytadi: `{"recorded", "score", "threshold", "attempts"}`.
        """
        body: dict[str, Any] = {
            "challenge": challenge,
            "faces_detected": faces_detected,
        }
        if score is not None:
            body["score"] = int(score)
        if not image and not reference_image:
            return self._api.post("/client/face/attempt/", json_body=body)
        return self._api.request(
            "POST",
            "/client/face/attempt/",
            files=_face_files(image, reference_image),
            data=body,
        )

    # --- 4. Operator shaxsni tasdiqlaydi -----------------------------
    def confirm_identity(self, *, document_type: str = "", document_number: str = "",
                         note: str = "") -> dict:
        """
        Operator shaxsni tasdiqlaydi.

        HUJJAT MA'LUMOTI IXTIYORIY va client uni YUBORMAYDI:
        operator hujjatni ekranda (jonli kadr + platformadan kelgan
        rasm) tekshiradi. Maydonlar shartnomada qoldirildi -
        boshqa o'rnatishda raqamni qayd etish talab qilinishi
        mumkin va o'shanda faqat chaqiruv o'zgaradi.

        Javobgarlik yo'qolmaydi: server tasdiqlagan xodimni va
        vaqtni `identity` meta'siga yozadi.
        """
        body = {"decision": "confirm"}
        if document_type:
            body["document_type"] = document_type
        if document_number:
            body["document_number"] = document_number
        if note:
            body["note"] = note
        return self._api.post("/client/identity/confirm/", json_body=body)

    def reject_identity(self, *, reason: str) -> dict:
        return self._api.post(
            "/client/identity/confirm/",
            json_body={"decision": "reject", "reason": reason},
        )

    # --- 5. Tashqi platformaga kirish --------------------------------
    def exam_access(self) -> dict:
        # IDEMPOTENT: havolani deshifrlab qaytaradi, holatni faqat bir
        # marta (`ready` -> `in_progress`) o'zgartiradi.
        return self._api.post("/client/exam/access/", idempotent=True)

    # --- Imtihon davomida --------------------------------------------
    # Davriy yuboruvchilar `retries=0`: takror va kutishni
    # `SessionMonitor` o'zi boshqaradi (backoff + jitter). So'rov ichida
    # ham takrorlansa, uzilishdan keyin yuk ikki-uch barobar bo'lardi.
    def heartbeat(self, **metrics) -> dict:
        return self._api.post("/client/heartbeat/", json_body=metrics, retries=0)

    def send_events(self, events: list[dict]) -> dict:
        # `client_event_id` dublikatni serverda to'sadi — batch'ni qayta
        # yuborish xavfsiz (navbat buni ishlatadi).
        return self._api.post("/client/events/", json_body={"events": events}, retries=0)

    def periodic_face(self, *, score: int, faces_detected: int = 1,
                      image: Optional[bytes] = None,
                      passed_since_last: int = 0) -> dict:
        """
        Test davomidagi tekshiruv - FAQAT MOS KELMAGANDA chaqiriladi.

        Solishtirish clientda: etalon `AppState.face_reference` da,
        jonli vektor esa kuzatuv oqimidan. Muvaffaqiyatli tekshiruvlar
        SERVERGA UMUMAN BORMAYDI - ularning soni heartbeat bilan
        ketadi (`face_checks`).

        `passed_since_last` - oxirgi xabardan keyingi muvaffaqiyatli
        tekshiruvlar soni. Usiz server "ketma-ket" qoidasini qo'llay
        olmasdi: u oradagi muvaffaqiyatlarni ko'rmaydi va ikki soat
        oralab kelgan uchta xato talabgorni chetlashtirib yuborardi.

        `embedding` YUBORILMAYDI: server uni solishtirmaydi va uni
        baribir uzatish "kim solishtiryapti?" degan savolni ochiq
        qoldirardi.
        """
        body: dict[str, Any] = {
            "score": int(score),
            "faces_detected": int(faces_detected),
            "passed_since_last": int(passed_since_last),
        }
        if not image:
            return self._api.post("/client/face/periodic/", json_body=body)
        return self._api.request(
            "POST",
            "/client/face/periodic/",
            files={"image": ("face.jpg", image, "image/jpeg")},
            data=body,
        )

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
            # Navbatning o'z backoff'i bor (`ScreenshotService`).
            retries=0,
        )

    def commit_screenshots(self, screenshots: list[dict]) -> dict:
        """
        Yuklangan skrinshotlar metadata'sini tasdiqlaydi (batch).

        Binary allaqachon storage'da; bu chaqiruv DB'ga yozuv qo'shadi.
        Backend chegarasi - bir so'rovda 50 ta.
        """
        return self._api.post(
            "/client/screenshots/commit/", json_body={"screenshots": screenshots},
            retries=0,
        )

    def upload_screenshot(self, *, data: bytes, captured_at: str,
                          question_id: str = "", question_number=None) -> dict:
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
            # Savol maydonlari FAQAT savol kadrida: bo'sh qiymat server
            # regex'idan o'tmasdi (eski server esa ularni e'tiborsiz qoldiradi).
            data={
                "captured_at": captured_at,
                **({"question_id": question_id} if question_id else {}),
                **({"question_number": str(question_number)} if question_number else {}),
            },
            retries=0,
        )

    def upload_evidence(self, *, kind: str, data: bytes, captured_at: str,
                        event_type: str = "", camera_role: str = "",
                        confidence: int = 0, duration_ms: int = 0,
                        boxes: Optional[list] = None) -> dict:
        """
        Shubhali hodisaning dalili (kadr yoki klip).

        Skrinshot yuklashdan ALOHIDA: dalilda hodisa konteksti bor
        (tur, kamera roli, ishonch, ramkalar) va u proktor ekranida
        hodisa yonida turadi. Skrinshot esa muntazam va kontekstsiz.

        `boxes` JSON SATR sifatida ketadi: `multipart/form-data`
        ichma-ich strukturani ko'tarmaydi va backend uni satrdan
        ochadi (`EvidenceUploadSerializer.validate_boxes`).

        Qaytadi: `{"id": ..., "kind": ..., "size": ...}` — `id`
        hodisaning `evidence_id` siga bog'lanadi.
        """
        name, content_type = (
            ("clip.mp4", "video/mp4") if kind == "clip" else ("frame.jpg", "image/jpeg")
        )
        return self._api.request(
            "POST",
            "/client/evidence/upload/",
            files={"file": (name, data, content_type)},
            data={
                "kind": kind,
                "captured_at": captured_at,
                "event_type": event_type,
                "camera_role": camera_role,
                "confidence": int(confidence),
                "duration_ms": int(duration_ms),
                "boxes": json.dumps(boxes or []),
            },
            retries=0,
        )

    def register_recording(self, *, kind: str, local_path: str, captured_at: str,
                           size_bytes: int = 0, duration_ms: int = 0,
                           width: int = 0, height: int = 0,
                           frames: int = 0, frames_dropped: int = 0,
                           event_type: str = "", camera_role: str = "",
                           confidence: int = 0, session_id: str = "",
                           timeout: Optional[float] = None) -> dict:
        """
        Mashinada QOLGAN yozuvning manzilini qayd etadi.

        FAYL YUBORILMAYDI va bu `upload_evidence` dan asosiy farq.
        Ekran yozuvi 3 soatlik imtihonda ~360 MB, kamera klipi esa
        hodisa sayin yig'iladi - 500 mashinali binoda bu kuniga
        yuzlab gigabayt degani va hech qanday kanalga sig'maydi.
        Serverga "qayerda yotibdi va qanaqa" degan ma'lumot boradi,
        proktor esa shu manzil bo'yicha mashinadan faylni so'raydi.

        Skrinshot bundan farq qiladi va AVVALGIDEK yuklanadi: u
        ~60 KB va proktorga imtihon davomida, real vaqtda kerak.

        JSON, `multipart` EMAS: yuboradigan fayl yo'q.

        `session_id` - sessiyaning `public_id` si va u HAR DOIM
        yuboriladi. Odatda server sessiyani tokendan topadi va bu
        qiymat faqat solishtiriladi; lekin proktor chetlashtirganda
        token client bilmasdan bekor bo'ladi va yozuv aynan o'shanda
        yakunlanadi - u holda sessiyani topishning yagona yo'li shu.
        """
        return self._api.post(
            "/client/recordings/",
            json_body={
                "kind": kind,
                "local_path": local_path,
                "captured_at": captured_at,
                "size_bytes": int(size_bytes),
                "duration_ms": int(duration_ms),
                "width": int(width),
                "height": int(height),
                "frames": int(frames),
                "frames_dropped": int(frames_dropped),
                "event_type": event_type,
                "camera_role": camera_role,
                "confidence": int(confidence),
                "session_id": session_id or None,
            },
            timeout=timeout,
            # Takroriy qayd yozuvni YANGILAYDI (yangisini yaratmaydi).
            idempotent=True,
        )

    # --- Yakunlash ----------------------------------------------------
    def finish_session(
        self, *, reason: str = "", completed: bool = False, timeout: Optional[float] = None
    ) -> dict:
        """
        `completed=True` — talabgor testni O'ZI yakunladi («Yakunlash»
        tugmasi): server kompyuter bronini bo'shatadi va joy keyingi
        talabgorga beriladi. Dasturdan chiqishdagi yakun uni YUBORMAYDI —
        talabgor testni topshirmagan va joyi saqlanishi kerak.
        """
        return self._api.post(
            "/client/session/finish/",
            json_body={"reason": reason, "completed": completed},
            timeout=timeout,
        )

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
