"""
Autentifikatsiya va qurilma identifikatori.

Bu servis UI'ga qaram emas va sinxron ishlaydi - uni `ApiWorker` fon
thread'idan chaqiriladi. Yagona istisno: `auth_expired` signali, u
`ApiClient` dan (istalgan thread'dan) keladi va Qt uni avtomatik UI
thread'ga marshal qiladi.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from config import APP_VERSION, DEVICE_ID_FILE, INVENTORY_CODE
from core.errors import ClientError, DeviceNotRegistered
from services import system_info
from services.api_client import ApiClient
from services.app_state import AppState, DeviceInfo, ExamOption, Staff
from services.repositories import AuthRepository, DeviceRepository, ProctoringRepository

log = logging.getLogger(__name__)


class AuthService(QObject):
    """Login, qurilma ro'yxati va handshake - bitta joyda."""

    #: Refresh ham yaroqsiz bo'lganda. `MainWindow` buni login sahifasiga
    #: qaytishga ulaydi.
    auth_expired = pyqtSignal()

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self._state = state
        self._api = ApiClient()
        self._auth_repo = AuthRepository(self._api)
        self._device_repo = DeviceRepository(self._api)
        self._client_repo = ProctoringRepository(self._api)
        self._refresh_token: str = ""
        self._api.set_auth_expired_handler(self.auth_expired.emit)
        self._api.set_device_id(self.load_device_id())

    # ------------------------------------------------------------------
    # Qurilma identifikatori
    # ------------------------------------------------------------------
    @staticmethod
    def load_device_id() -> str:
        """
        `device_id` ni diskdan o'qiydi.

        U kredensial emas, shuning uchun shifrlanmaydi. Lekin YO'QOLMASLIGI
        kerak: har ishga tushishda yangisini olish backendda cheksiz
        `PENDING` qatorlar hosil qiladi va admin har safar qaytadan
        tasdiqlashga majbur bo'ladi.
        """
        try:
            if DEVICE_ID_FILE.exists():
                data = json.loads(DEVICE_ID_FILE.read_text(encoding="utf-8"))
                return str(data.get("device_id") or "")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("device_id o'qilmadi: %s", exc)
        return ""

    @staticmethod
    def save_device_id(device_id: str) -> None:
        try:
            DEVICE_ID_FILE.write_text(
                json.dumps({"device_id": device_id}), encoding="utf-8"
            )
        except OSError as exc:
            log.error("device_id saqlanmadi: %s", exc)

    @staticmethod
    def reset_device() -> None:
        """Saqlangan `device_id` ni o'chiradi (qayta ro'yxatdan o'tish uchun)."""
        try:
            DEVICE_ID_FILE.unlink(missing_ok=True)
        except OSError as exc:
            log.error("device_id faylini o'chirib bo'lmadi: %s", exc)

    def ensure_device(self) -> str:
        """
        Qurilma ro'yxatdan o'tganiga ishonch hosil qiladi.

        Ro'yxatdan o'tish OCHIQ endpoint va yangi qurilma `PENDING`
        holatida tug'iladi - admin tasdiqlamaguncha handshake 401 beradi.
        Bu holat xato emas, shuning uchun bu yerda istisno tashlanmaydi:
        login sahifasi operatorga "administrator tasdig'ini kuting" deb
        ko'rsatadi.
        """
        device_id = self.load_device_id()
        if device_id:
            self._api.set_device_id(device_id)
            return device_id

        log.info("device_id topilmadi - qurilma ro'yxatga qo'yilmoqda")
        try:
            result = self._device_repo.register(
                app_version=APP_VERSION, inventory_code=INVENTORY_CODE
            )
            device_id = str((result or {}).get("device_id") or "")
        except ClientError as exc:
            # Kompyuterda allaqachon faol token bor. Agar apparat izi mos
            # kelsa (ya'ni bu O'SHA mashina), server mavjud
            # identifikatorni qaytaradi va client o'zini tiklaydi.
            # Aks holda `device_id` berilmaydi va xato yuqoriga ketadi.
            if exc.code != "device_already_registered":
                raise
            device_id = str((exc.details or {}).get("device_id") or "")
            if not device_id:
                raise
            log.info("Mavjud qurilma identifikatori tiklandi")

        if device_id:
            self.save_device_id(device_id)
            self._api.set_device_id(device_id)
        return device_id

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> Staff:
        """
        Xodim login qiladi va oqim uchun kerakli hamma narsa yuklanadi.

        Ketma-ketlik ataylab shunday: avval qurilma (usiz `X-Device-ID`
        bo'lmaydi), keyin login, keyin handshake. Handshake login'dan
        oldin ishlamaydi - u xodim JWT'sini talab qiladi.
        """
        # 1. Qurilma - login'dan OLDIN. Ro'yxatdan o'tish ochiq endpoint,
        #    JWT talab qilmaydi.
        try:
            self.ensure_device()
        except ClientError as exc:
            # Kompyuter bazaga qo'shilmagan bo'lsa (404) - bu operator
            # hal qila olmaydigan holat, lekin login'ni to'smaymiz:
            # aniq xabar handshake'dan keyin ko'rsatiladi.
            log.warning("Qurilmani ro'yxatga qo'yib bo'lmadi: %s", exc)

        # 2. Xodim JWT'si
        payload = self._auth_repo.login(username, password) or {}
        access = payload.get("access") or ""
        refresh = payload.get("refresh") or ""
        if not access:
            raise ClientError("Server tokensiz javob qaytardi", code="invalid_response")
        self._refresh_token = refresh
        self._api.set_tokens(access, refresh)

        staff = Staff.from_api(payload.get("user") or {})
        self._state.staff = staff
        log.info("Kirish: %s (%s)", staff.username, staff.role_name or "-")
        return staff

    def handshake(self, *, refresh_machine: bool = False) -> DeviceInfo:
        """
        Kompyuter, bino, kameralar va bugungi imtihonlar ro'yxati.

        Bu chaqiruv oqimning "kalitini" beradi: usiz qaysi binoda
        turganimizni ham, qaysi imtihonlar ochiqligini ham bilmaymiz.

        MASHINA IDENTIFIKATORI HAM SHU YERDA yuboriladi (Machine UUID;
        MAC va IP - ikkilamchi) va server uni `Computer.machine_uuid`
        bilan solishtiradi. Alohida
        endpoint qilinmadi: tekshiruv natijasi handshake bergan
        kontekstga (bino, kompyuter) bog'liq va ikkinchi so'rov ikkala
        javobning bir-biriga mos kelishini kafolatlay olmasdi -
        oradagi soniyalarda administrator kompyuterni ko'chirishi
        mumkin.

        `refresh_machine=True` - MAC/IP keshdan emas, QAYTADAN
        o'lchanadi. "Yangilash" tugmasi aynan shuni so'raydi:
        operator tarmoq kabelini almashtirgan yoki adapterni yoqqan
        bo'lishi mumkin va eski qiymat bilan yangilash hech narsani
        o'zgartirmasdi.
        """
        machine = self._machine_identity(refresh=refresh_machine)
        # Sahifalar shu yerdan o'qiydi (`AppState.machine`): ekranda
        # ko'rinadigan MAC/IP serverga yuborilgani bilan AYNAN bir xil
        # bo'lishi kerak, aks holda "panelda boshqa, ekranda boshqa"
        # degan tushuntirib bo'lmaydigan holat chiqadi.
        if machine:
            self._state.machine = dict(machine)
        hardware = self._hardware_report()
        try:
            data = self._client_repo.handshake(
                app_version=APP_VERSION, hardware=hardware, machine=machine
            ) or {}
        except DeviceNotRegistered:
            # Server bu `device_id` ni bilmaydi. Sabab odatda serverda:
            # token o'chirilgan (baza tozalangan, qurilma qayta
            # yaratilgan, test skripti tozalab ketgan). Client esa eski
            # identifikatorni diskda saqlab turadi va O'ZI hech qachon
            # bu holatdan chiqa olmaydi - operator uchun bu "hech narsa
            # ishlamayapti" degani, chunki %APPDATA% ni tozalash uning
            # ishi emas.
            #
            # Shuning uchun BIR MARTA qayta ro'yxatdan o'tamiz. Bu
            # xavfsiz: yangi qurilma `PENDING` bo'lib tug'iladi va
            # keyingi handshake `device_not_approved` qaytaradi, ya'ni
            # tasdiqsiz hech narsa ochilmaydi.
            log.warning("Saqlangan device_id serverda topilmadi - qayta ro'yxatdan o'tilmoqda")
            self.reset_device()
            self.ensure_device()
            data = self._client_repo.handshake(
                app_version=APP_VERSION, hardware=hardware, machine=machine
            ) or {}

        device_data = data.get("device") or {}
        computer = data.get("computer") or {}
        device = DeviceInfo(
            device_id=device_data.get("device_id") or "",
            status=device_data.get("status") or "unregistered",
            number=computer.get("number"),
            inventory_code=computer.get("inventory_code", ""),
            computer_label=computer.get("label", "") or computer.get("inventory_code", ""),
            zone_id=computer.get("zone_id"),
            zone_name=computer.get("zone_name", ""),
            cameras=list(data.get("cameras") or []),
            machine=dict(data.get("machine") or {}),
        )
        self._state.device = device
        self._state.config = data.get("config") or {}
        self._state.exams = [ExamOption.from_api(item) for item in (data.get("exams") or [])]
        if not device.machine_allowed:
            log.warning(
                "Mashina tekshiruvidan o'tmadi (%s): %s",
                device.machine.get("status") or "-",
                device.machine_message,
            )
        log.info(
            "Handshake: bino=%s kamera=%s imtihon=%s",
            device.zone_name or "-",
            len(device.cameras),
            len(self._state.exams),
        )
        return device

    @staticmethod
    def _machine_identity(*, refresh: bool = False) -> dict:
        """
        MAC va IP - bitta adapterdan (`system_info.machine_identity`).

        Xato YUTILADI: manzilni aniqlab bo'lmasa handshake baribir
        ketadi va server tekshiruvni "noma'lum" deb belgilaydi. Bu
        yerda to'xtash noto'g'ri bo'lardi - qaror serverda, client
        esa faqat o'lchaydi.
        """
        try:
            return system_info.machine_identity(refresh=refresh)
        except Exception:
            log.warning("Mashina identifikatori aniqlanmadi", exc_info=True)
            return {}

    @staticmethod
    def _hardware_report() -> dict:
        """
        Apparat xabari (GPU va unumdorlik profili).

        Import KECHIKTIRILGAN va xato YUTILADI: `proctoring/` — AI
        qatlami va u imtihon oqimining ishlashi uchun shart emas
        (`proctoring/__init__.py` shartnomasi). Apparat aniqlanmasa
        handshake apparatsiz ketadi va operator hech narsani
        sezmaydi; server esa eski qiymatni saqlab qoladi.

        Kutish YO'Q (`timeout=0`): aniqlash dastur ishga tushganda
        fon thread'ida boshlangan va login formasini to'ldirish
        vaqtida odatda tugaydi. Tugmagan bo'lsa - keyingi
        handshake yozadi.
        """
        try:
            from proctoring.hardware import report

            return report()
        except Exception:
            log.debug("Apparat xabari tayyorlanmadi", exc_info=True)
            return {}

    # ------------------------------------------------------------------
    def logout(self) -> None:
        """Lokal holat DARHOL tozalanadi, server chaqiruvi best-effort."""
        refresh = self._refresh_token
        self._refresh_token = ""
        self._state.reset_all()
        self._api.set_session_token(None)
        try:
            if refresh:
                self._auth_repo.logout(refresh)
        finally:
            self._api.clear()

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def staff(self) -> Optional[Staff]:
        return self._state.staff
