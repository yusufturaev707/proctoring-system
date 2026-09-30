import logging

from django.conf import settings
from django.utils import timezone
from django.db.models import OuterRef, Prefetch, Subquery
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import (
    AuditLogMixin,
    BulkSelectionMixin,
    PermissionRequiredMixin,
    SoftDeleteRestoreMixin,
)
from apps.common.permissions import HasRolePermission
from apps.common.throttling import DeviceRegisterThrottle, client_ip
from apps.common.utils.network import is_private_ip
from apps.common.utils.validators import normalize_mac, normalize_machine_uuid
from apps.devices import selectors, services
from apps.devices.api.v1.serializers import (
    CameraSerializer,
    ComputerSerializer,
    DeviceRegisterSerializer,
    DeviceTokenSerializer,
)
from apps.devices.models import Camera, Computer, DeviceToken
from apps.proctoring.services.audit import record_audit

logger = logging.getLogger(__name__)

#: Jonli ko'rish qismlari chegarasi (MJPEG).
_LIVE_BOUNDARY = "cameraframe"


def _live_slots():
    import threading

    return threading.BoundedSemaphore(max(1, int(getattr(settings, "CAMERA_LIVE_MAX_STREAMS", 2))))


#: Jarayon ichida bir vaqtdagi jonli oqimlar chegarasi
#: (`CAMERA_LIVE_MAX_STREAMS`).
_LIVE_SLOTS = _live_slots()


class ComputerViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, BulkSelectionMixin,
    viewsets.ModelViewSet,
):
    serializer_class = ComputerSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "devices.manage"
    required_read_permission = "devices.view"
    audit_object_type = "Computer"
    filterset_fields = ["zone", "zone__region", "status", "is_active"]
    search_fields = ["number", "inventory_code", "machine_uuid", "ip_address", "mac_address"]
    # Jadvaldagi har saralanadigan ustun shu ro'yxatda bo'lishi shart —
    # aks holda DRF `?ordering=` ni jimgina e'tiborsiz qoldiradi.
    ordering_fields = [
        "id", "number", "inventory_code", "ip_address", "mac_address",
        "machine_uuid", "status", "last_seen_at",
    ]

    def get_queryset(self):
        from apps.proctoring.models import ExamSession

        # Har bir kompyuter uchun joriy faol sessiyani bitta subquery bilan
        # olamiz — N+1 o'rniga bitta so'rov.
        active_session = ExamSession.objects.filter(
            computer_id=OuterRef("pk"),
            status__in=[
                ExamSession.Status.IN_PROGRESS,
                ExamSession.Status.READY,
                ExamSession.Status.FACE_CHECK,
            ],
        ).values("pk")[:1]

        queryset = self.apply_deleted_filter(
            selectors.computers_base(include_deleted=True)
        ).annotate(active_session_id=Subquery(active_session))
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)
        if self.action in ("retrieve", "list"):
            # Filtrsiz `prefetch_related("cameras")` ikki muammo berardi:
            # M2M through-jadvali yumshoq o'chirishda tozalanmaydi, ya'ni
            # hisobdan chiqarilgan kamera kompyuter kartochkasida ko'rinib
            # turardi; `select_related` yo'qligi esa `cameras_detail` dagi
            # har bir `zone_name`/`region_name` uchun qo'shimcha so'rov
            # keltirib chiqarardi. `cameras_base()` ikkalasini ham yopadi.
            queryset = queryset.prefetch_related(
                Prefetch("cameras", queryset=selectors.cameras_base())
            )
        return queryset

    @extend_schema(request=None, responses={(200, "application/octet-stream"): bytes})
    @action(detail=False, methods=["get"], url_path="import-template")
    def import_template(self, request):
        """Excel shablon (`computer_import.COLUMNS`) — faqat o'qish ruxsati."""
        from django.http import HttpResponse

        from apps.devices.computer_import import build_template

        # `HttpResponse`, DRF `Response` EMAS: `ApiJSONRenderer` baytlarni
        # `{success, data}` konvertiga o'rab buzardi.
        response = HttpResponse(
            build_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="kompyuterlar_shablon.xlsx"'
        return response

    @extend_schema(request={"multipart/form-data": {"type": "object"}}, responses=None)
    @action(detail=False, methods=["post"], url_path="import")
    def import_excel(self, request):
        """
        Excel'dan ommaviy qo'shish (`computer_import.py`).

        `dry_run=true` — faqat tekshiruv (panel avval shuni chaqiradi).
        Xato bo'lsa hech narsa yozilmaydi va 200 bilan hisobot qaytadi:
        bu "so'rov buzilgan" emas, "fayl tuzatilishi kerak" degan javob
        va panel uni jadval qilib ko'rsatadi. Faylning o'zi o'qilmasa — 400.
        """
        from apps.devices.computer_import import ImportFileError, import_computers, read_rows

        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Excel fayl yuklanmagan."})
        dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
        try:
            rows = read_rows(upload)
        except ImportFileError as exc:
            raise serializers.ValidationError({"file": str(exc)})

        report = import_computers(rows, user=request.user, dry_run=dry_run)
        if report["created"] or report["bound"]:
            self.log_audit("import", meta={
                "file": upload.name, "created": report["created"],
                # UUID'si to'ldirilgan mavjud kompyuterlar - yozuv
                # o'zgargani auditda ko'rinishi shart.
                "bound": report["bound"],
                "skipped": len(report["skipped"]),
            })
        return Response(report)

    @extend_schema(request=None, responses=None)
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """
        Tanlangan kompyuterlarni o'chirish (yumshoq — "Savat"dan tiklanadi).

        IMTIHONDAGI MASHINA O'TKAZIB YUBORILADI: bittasini o'chirishda
        administrator qatorni ko'rib turadi, 500 talik tanlovda esa hozir
        imtihon ketayotgan mashina ko'rinmay qolishi mumkin — uning
        sessiyasi o'chirilgan kompyuterga yozilib qolardi. Javobda nechtasi
        o'tkazib yuborilgani aytiladi. Audit — BITTA yozuv (ID'lar bilan).
        """
        selected = self.bulk_queryset().filter(deleted_at__isnull=True)
        in_exam = list(
            selected.filter(active_session_id__isnull=False).values_list("pk", flat=True)
        )
        ids = list(selected.exclude(pk__in=in_exam).values_list("pk", flat=True))
        if ids:
            now = timezone.now()
            Computer.objects.filter(pk__in=ids).update(deleted_at=now, updated_at=now)
            self.log_audit("delete", meta={"action": "bulk_delete", "count": len(ids), "ids": ids[:1000]})
        return Response({"deleted": len(ids), "skipped_in_exam": len(in_exam)})


class CameraViewSet(
    PermissionRequiredMixin, AuditLogMixin, SoftDeleteRestoreMixin, viewsets.ModelViewSet
):
    serializer_class = CameraSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "devices.manage"
    required_read_permission = "devices.view"
    audit_object_type = "Camera"
    filterset_fields = ["zone", "zone__region", "status", "is_active"]
    search_fields = ["name", "ip_address", "mac_address"]

    def get_queryset(self):
        queryset = self.apply_deleted_filter(selectors.cameras_base(include_deleted=True))
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(zone__region_id=user.region_id)
        return queryset

    @extend_schema(request=None, responses=CameraSerializer)
    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """
        Kamerani HOZIR tekshiradi (RTSP `DESCRIBE`) va yangi holatni qaytaradi.

        Davriy tekshiruv daqiqada bir marta; administrator esa kamerani
        tuzatgach natijani darhol ko'rishi kerak - bir daqiqa kutish
        "tuzatdimmi?" degan savolni ochiq qoldirardi.
        """
        camera = self.get_object()
        services.check_camera(camera)
        return Response(self.get_serializer(camera).data)

    @extend_schema(responses={(200, "image/jpeg"): bytes})
    @action(detail=True, methods=["get"])
    def snapshot(self, request, pk=None):
        """
        Kameraning ENG YANGI kadri (JPEG) - paneldagi jonli ko'rish uchun.

        Panel buni sekundiga bir necha marta so'raydi; oqim serverda
        bitta o'quvchi tomonidan ochiq turadi (`camera_live.py`).

        RUXSAT `devices.manage` - ko'rish (GET) bo'lsa ham: bu imtihon
        xonasining JONLI tasviri va ro'yxatni ko'rish huquqi
        (`devices.view`) uni ochmasligi kerak. Har ko'rish audit'da
        qoladi (takrorlar 10 daqiqa ichida bitta yozuvga yig'iladi -
        aks holda har kadr alohida yozuv bo'lardi).
        """
        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponse

        from apps.devices import camera_live

        user = request.user
        if not (user.is_superuser or user.has_role_permission("devices.manage")):
            raise PermissionDenied("Kamera tasvirini ko'rish uchun ruxsat yo'q")

        from apps.common.exceptions import (
            CameraInactive,
            CameraStreamUnavailable,
            CameraViewerUnavailable,
        )

        camera = self.get_object()
        if not camera.is_active or camera.deleted_at is not None:
            raise CameraInactive()
        self._audit_live_view(camera)
        try:
            jpeg, taken_at = camera_live.snapshot(camera, services.build_rtsp_url(camera))
        except ImportError as exc:
            raise CameraViewerUnavailable() from exc
        except camera_live.CameraUnavailable as exc:
            raise CameraStreamUnavailable(str(exc)) from exc

        response = HttpResponse(jpeg, content_type="image/jpeg")
        # Kadr qachon olingani - panel "N soniya oldin" deb ko'rsatadi:
        # oqim to'xtab qolsa, eski kadr "jonli" bo'lib ko'rinmasligi kerak.
        response["X-Frame-Taken-At"] = "{:.3f}".format(taken_at)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(responses={(200, "multipart/x-mixed-replace"): bytes})
    @action(detail=True, methods=["get"])
    def live(self, request, pk=None):
        """
        JONLI oqim - MJPEG (`multipart/x-mixed-replace`), bitta uzun javob.

        Har kadr yangi kelishi bilan yuboriladi (~12 kadr/s). Har
        qismda `X-Frame-Taken-At` (kadr olingan payt) va
        `X-Frame-Sent-At` (yuborilgan payt) - panel server ichidagi
        kechikishni shulardan ko'rsatadi.

        `X-Accel-Buffering: no` - nginx javobni buferlamasin: aks holda
        u kadrlarni to'plab, bir necha soniyalik bo'laklarda uzatardi.

        Ruxsat, audit va xatolar `snapshot` bilan BIR XIL.
        """
        from django.core.exceptions import PermissionDenied
        from django.http import StreamingHttpResponse

        from apps.common.exceptions import (
            CameraInactive,
            CameraStreamUnavailable,
            CameraViewerBusy,
            CameraViewerUnavailable,
        )
        from apps.devices import camera_live

        user = request.user
        if not (user.is_superuser or user.has_role_permission("devices.manage")):
            raise PermissionDenied("Kamera tasvirini ko'rish uchun ruxsat yo'q")
        camera = self.get_object()
        if not camera.is_active or camera.deleted_at is not None:
            raise CameraInactive()

        if not _LIVE_SLOTS.acquire(blocking=False):
            raise CameraViewerBusy()
        released = False

        def release():
            nonlocal released
            if not released:
                released = True
                _LIVE_SLOTS.release()

        try:
            self._audit_live_view(camera)
            frames = camera_live.open_stream(
                camera,
                services.build_rtsp_url(camera),
                max_seconds=float(getattr(settings, "CAMERA_LIVE_STREAM_SECONDS", 60)),
            )
        except ImportError as exc:
            release()
            raise CameraViewerUnavailable() from exc
        except camera_live.CameraUnavailable as exc:
            release()
            raise CameraStreamUnavailable(str(exc)) from exc
        except Exception:
            release()
            raise

        def body():
            import time as _time

            try:
                for jpeg, taken_at in frames:
                    head = (
                        "--{b}\r\nContent-Type: image/jpeg\r\nContent-Length: {n}\r\n"
                        "X-Frame-Taken-At: {t:.3f}\r\nX-Frame-Sent-At: {s:.3f}\r\n\r\n"
                    ).format(b=_LIVE_BOUNDARY, n=len(jpeg), t=taken_at, s=_time.time())
                    yield head.encode("ascii") + jpeg + b"\r\n"
            finally:
                # Ko'ruvchi oynani yopdi yoki oqim tugadi - joy bo'shaydi.
                release()

        response = StreamingHttpResponse(
            body(), content_type="multipart/x-mixed-replace; boundary={}".format(_LIVE_BOUNDARY)
        )
        response["Cache-Control"] = "no-store"
        response["X-Accel-Buffering"] = "no"
        return response

    def _audit_live_view(self, camera) -> None:
        from apps.common.redis_client import get_redis

        key = "cam:live:audit:{}:{}".format(self.request.user.pk, camera.pk)
        try:
            if not get_redis().set(key, "1", ex=600, nx=True):
                return
        except Exception:
            # Redis yo'q - yozuv takrorlanadi, lekin ko'rish TO'XTAMAYDI.
            logger.debug("Kamera ko'rish auditini Redis'da qayd etib bo'lmadi", exc_info=True)
        record_audit(
            actor=self.request.user,
            action="camera_live_view",
            object_type="Camera",
            object_id=camera.pk,
            meta={"name": camera.name, "zone": camera.zone_id},
            request=self.request,
        )


class DeviceTokenViewSet(
    PermissionRequiredMixin, AuditLogMixin, BulkSelectionMixin, viewsets.ModelViewSet
):
    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated, HasRolePermission]
    required_permission = "devices.manage"
    required_read_permission = "devices.view"
    audit_object_type = "DeviceToken"
    http_method_names = ["get", "post", "patch", "head", "options"]
    # `performance_profile` filtr sifatida MUHIM: "qaysi mashinalar CPU
    # rejimida ishlayapti?" — aynan o'sha mashinalarda kuzatuv sifati
    # past va ularni oldindan bilish kerak, imtihon kunida emas.
    filterset_fields = [
        "status", "computer", "computer__zone", "computer__zone__region",
        "performance_profile",
    ]
    search_fields = [
        "device_id", "hardware_fingerprint", "app_version", "gpu_name",
        "reported_machine_uuid", "reported_mac",
        "computer__number",
        "computer__inventory_code",
        "computer__machine_uuid",
    ]
    ordering_fields = ["last_used_at", "created_at", "status"]

    def _scoped(self):
        """Foydalanuvchi ko'ra oladigan qurilmalar (viloyat doirasi)."""
        queryset = selectors.device_tokens_base()
        user = self.request.user
        if user.is_region_scoped:
            queryset = queryset.filter(computer__zone__region_id=user.region_id)
        return queryset

    def get_queryset(self):
        queryset = self._scoped()

        # `?online=true` — faqat HOZIR ishlab turgan clientlar.
        #
        # Filtr SQL'da emas, Redis'da: presence TTL bilan yashaydi va
        # uni DB'ga ko'chirish "har signalda UPDATE" degani bo'lardi
        # (`devices.services.touch_presence` izohi). Ro'yxat katta
        # emas - qurilmalar soni mashinalar soniga teng.
        online = (self.request.query_params.get("online") or "").lower()
        if online in ("true", "false", "1", "0"):
            wanted = online in ("true", "1")
            ids = set(services.presence_map(
                queryset.values_list("device_id", flat=True)
            ))
            queryset = (
                queryset.filter(device_id__in=ids)
                if wanted
                else queryset.exclude(device_id__in=ids)
            )
        return queryset

    def get_serializer_context(self):
        """
        Sahifadagi qurilmalar uchun presence — BITTA `MGET`.

        Serializer buni o'zi ham so'ray oladi, lekin o'shanda har
        qatorda alohida Redis chaqiruvi bo'lardi.
        """
        context = super().get_serializer_context()
        page = getattr(self, "_page_devices", None)
        if page is not None:
            context["presence"] = services.presence_map(page)
        return context

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        if page is not None:
            self._page_devices = [item.device_id for item in page]
        return page

    def perform_update(self, serializer):
        """Yagona yoziladigan maydon — `computer` (qayta biriktirish)."""
        previous = serializer.instance.computer_id
        instance = serializer.save()
        self.log_audit(
            "update", instance,
            {"action": "rebind", "computer_from": previous, "computer_to": instance.computer_id},
        )
        return instance

    @extend_schema(responses={200: DeviceTokenSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """
        Qurilmani faollashtiradi: kutayotganini TASDIQLAYDI, bloklanganini
        BLOKDAN CHIQARADI.

        Ikkinchisi ilgari panelda umuman yo'q edi: `device_id` diskdagi
        fayl va client uni o'zgartirmaydi, ya'ni xato bloklangan mashina
        abadiy yopiq qolardi. Faol qurilmada hech narsa qilinmaydi —
        takroriy bosish audit jurnalini to'ldirmasligi kerak.
        """
        device = self.get_object()
        previous = device.status
        if previous != DeviceToken.Status.ACTIVE:
            services.approve_device(device)
            self.log_audit(
                "update", device,
                {"action": "unblock" if previous == DeviceToken.Status.REVOKED else "approve"},
            )
        return Response(self.get_serializer(device).data)

    @extend_schema(request=None, responses=None)
    @action(detail=False, methods=["post"], url_path="bulk-approve")
    def bulk_approve(self, request):
        """
        Tanlangan qurilmalarni BIRDANIGA tasdiqlash.

        Yangi bino ulanganda yuzlab client bir vaqtda ro'yxatdan o'tadi va
        ularni bittalab tasdiqlash imtihon oldidan jismonan ulgurmaydi.
        FAQAT KUTAYOTGANLAR tasdiqlanadi: bloklangan qurilma — kimningdir
        ongli qarori va uni blokdan chiqarish bittalab, sababni ko'rib
        qilinadi (`approve/`). Audit — BITTA yozuv (ID'lar bilan).
        """
        selected = self.bulk_queryset()
        ids = list(
            selected.filter(status=DeviceToken.Status.PENDING).values_list("pk", flat=True)
        )
        skipped = selected.exclude(pk__in=ids).count()
        if ids:
            DeviceToken.objects.filter(pk__in=ids).update(
                status=DeviceToken.Status.ACTIVE, revoked_at=None, revoke_reason="",
                updated_at=timezone.now(),
            )
            self.log_audit("update", meta={"action": "bulk_approve", "count": len(ids), "ids": ids[:1000]})
        return Response({"approved": len(ids), "skipped": skipped})

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        """
        Qurilmani bloklaydi — SABAB MAJBURIY.

        Ilgari sababni faqat panel so'rardi, API esa bo'sh satrni ham
        qabul qilardi. Blok — operator "nega bu mashinada imtihon
        ochilmayapti?" deb so'raganda javob beradigan yagona yozuv.
        """
        device = self.get_object()
        reason = str((request.data or {}).get("reason", "") or "").strip()
        if not reason:
            raise serializers.ValidationError({"reason": ["Blok sababini yozing"]})
        if device.status != DeviceToken.Status.REVOKED:
            services.revoke_device(device, reason=reason)
            self.log_audit("device_revoke", device, {"reason": reason})
        return Response(self.get_serializer(device).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """
        Holatlar bo'yicha sonlar — panel tab'larida.

        Ilgari sahifa «Kutilmoqda» tabida ochilar va u bo'sh bo'lsa,
        administrator na tasdiqlashni kutayotgan, na faol qurilmalar
        sonini ko'rardi. Viloyat doirasi ro'yxatdagi bilan bir xil.
        """
        from django.db.models import Count

        scoped = self._scoped()
        counts = {
            row["status"]: row["total"]
            for row in scoped.order_by().values("status").annotate(total=Count("id"))
        }
        online = len(services.presence_map(scoped.values_list("device_id", flat=True)))
        return Response({
            "pending": counts.get(DeviceToken.Status.PENDING, 0),
            "active": counts.get(DeviceToken.Status.ACTIVE, 0),
            "revoked": counts.get(DeviceToken.Status.REVOKED, 0),
            "total": sum(counts.values()),
            "online": online,
        })


def _is_same_machine(computer: Computer, existing: DeviceToken, data: dict) -> bool:
    """
    Ro'yxatdan o'tayotgan mashina - kompyuterning mavjud tokeni egasimi.

    Qaror (UUID, MAC) JUFTLIGI bo'yicha: so'rovdagi juftlik kompyuter
    yozuvidagiga aynan teng. Faqat apparat iziga TAYANILMAYDI: `muid:<UUID>`
    izi bir partiyadagi (UUID'i bir xil) platalarda bir xil edi va ikkinchi
    mashina birinchisining `device_id` sini olib qo'yardi.

    Juftlikni solishtirib bo'lmaydigan ESKI holatlar - yozuvda UUID yoki
    MAC yo'q, yoki client UUID yubormaydi - avvalgidek iz bo'yicha (format
    o'tishlari bilan, `fingerprint_matches`).
    """
    machine_uuid = normalize_machine_uuid(data.get("machine_uuid"))
    mac = normalize_mac(data.get("mac_address")) or ""
    record_mac = normalize_mac(computer.mac_address) or ""
    if machine_uuid and computer.machine_uuid and record_mac:
        return machine_uuid == computer.machine_uuid and mac == record_mac
    if machine_uuid and computer.machine_uuid and machine_uuid != computer.machine_uuid:
        return False
    return services.fingerprint_matches(
        existing.hardware_fingerprint,
        (data.get("hardware_fingerprint") or "")[:128],
        mac,
        computer.mac_address,
    )


class DeviceRegisterView(APIView):
    """
    Client o'zini ro'yxatga qo'yadi.

    Ochiq endpoint, lekin yaratilgan qurilma `PENDING` holatida bo'ladi va
    admin tasdiqlamaguncha hech qanday so'rov qabul qilinmaydi. Bu yerda
    hech qanday sir berilmaydi — client so'rovlarini xodim JWT'si
    himoyalaydi, `device_id` esa maxfiy qiymat emas.
    """

    permission_classes: list = []
    authentication_classes: list = []
    # `REST_FRAMEWORK` da `DEFAULT_THROTTLE_CLASSES` YO'Q — chegara har bir
    # view'ga qo'lda ulanadi. Ochiq endpointda buni unutish mumkin emas.
    throttle_classes = [DeviceRegisterThrottle]

    @extend_schema(request=DeviceRegisterSerializer, responses={201: None})
    def post(self, request):
        serializer = DeviceRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Binoni so'rovning TASHQI (NAT) IP'si bo'yicha aniqlaymiz.
        # Bu ikki narsa uchun kerak: LAN IP bo'yicha moslashtirishni
        # to'g'ri binoga cheklash va avtomatik inventarizatsiya.
        observed_ip = client_ip(request)
        zone = services.resolve_zone_by_public_ip(observed_ip)

        # Server bino ICHIDA tursa, u client'ning LAN manzilini ko'radi
        # (marshrutda NAT yo'q) va binoni tashqi IP orqali aniqlay
        # olmaydi. Shu holatda client o'zi aniqlagan tashqi manzil
        # zaxira signal bo'lib ishlaydi.
        #
        # Bu qiymat ISHONCHSIZ (client uni yozib yuboradi), shuning uchun
        # u FAQAT bino tanlashda va faqat server ko'rgan manzil xususiy
        # bo'lganda ishlatiladi. Kirish ruxsatini u hech qachon hal
        # qilmaydi - `check_source_ip` baribir server ko'rgan manzilga
        # qaraydi.
        reported_ip = data.get("public_ip", "")
        if zone is None and reported_ip and is_private_ip(observed_ip):
            zone = services.resolve_zone_by_public_ip(reported_ip)
            if zone is not None:
                logger.info(
                    "Bino client aytgan tashqi IP orqali aniqlandi: %s -> %s "
                    "(server ko'rgan manzil: %s)",
                    reported_ip, zone, observed_ip,
                )

        public_ip = reported_ip or observed_ip

        computer = services.resolve_computer(
            machine_uuid=data.get("machine_uuid", ""),
            mac_address=data.get("mac_address", ""),
            ip_address=data.get("ip_address", ""),
            inventory_code=data.get("inventory_code", ""),
            zone=zone,
        )

        if computer is None and settings.PROCTORING["AUTO_REGISTER_COMPUTERS"]:
            computer = services.auto_create_computer(
                zone=zone,
                machine_uuid=data.get("machine_uuid", ""),
                mac_address=data.get("mac_address", ""),
                ip_address=data.get("ip_address", ""),
                inventory_code=data.get("inventory_code", ""),
            )
            if computer is not None:
                record_audit(
                    actor=None,
                    action="create",
                    object_type="Computer",
                    object_id=computer.pk,
                    meta={
                        "auto": True,
                        "public_ip": public_ip,
                        "machine_uuid": computer.machine_uuid or "",
                        "mac_address": computer.mac_address,
                        "zone": str(zone),
                    },
                    request=request,
                )

        if computer is None:
            logger.info(
                "Qurilma ro'yxatdan o'ta olmadi: uuid=%s mac=%s lan_ip=%s public_ip=%s bino=%s",
                data.get("machine_uuid") or "-",
                data.get("mac_address") or "-",
                data.get("ip_address") or "-",
                public_ip,
                zone or "aniqlanmadi",
            )
            return Response(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "computer_not_found",
                        "message": (
                            "Bu kompyuter bazada topilmadi. Administrator uni "
                            "Machine UUID bilan ro'yxatga qo'shishi kerak."
                        ),
                        "details": {
                            "machine_uuid": data.get("machine_uuid", ""),
                            "mac_address": data.get("mac_address", ""),
                            "observed_ip": observed_ip,
                            # Bino aniqlanmagani ko'pincha asosiy sabab:
                            # binoning tashqi IP'si `AllowedPublicIp` da yo'q.
                            "zone_resolved": zone is not None,
                            "public_ip": public_ip,
                        },
                    },
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Bu kompyuter uchun avvaldan faol token bormi?
        existing = DeviceToken.objects.filter(
            computer=computer, status=DeviceToken.Status.ACTIVE
        ).first()
        if existing is not None:
            # Client `device_id` ni yo'qotgan bo'lishi mumkin (%APPDATA%
            # tozalangan, dastur boshqa profilda ishga tushgan). Bunda u
            # o'zi hech qachon tiklanolmaydi: yangi token berilmaydi,
            # eskisi esa unga noma'lum.
            #
            # Shuning uchun mavjud identifikator FAQAT so'rov o'sha
            # mashinadan kelayotgani isbotlanganda qaytariladi. Aks holda
            # (bir kompyuterni ikki mashina o'ziniki deb da'vo qilyapti) ID
            # berilmaydi va masalani administrator hal qiladi.
            same_machine = _is_same_machine(computer, existing, data)
            if not same_machine:
                logger.warning(
                    "Qurilma qayta ro'yxatdan o'tmoqchi, lekin mashina boshqa: "
                    "pc=%s mavjud_iz=%s kelgan_iz=%s",
                    computer.inventory_code,
                    existing.hardware_fingerprint[:16] or "-",
                    (data.get("hardware_fingerprint") or "")[:16] or "-",
                )

            # Javob konvertga ATAYLAB qo'lda o'raladi: `ApiJSONRenderer`
            # tayyor konvertni qayta o'ramaydi, shu tarzda `code` va
            # `details` client uchun barqaror shaklda yetib boradi.
            return Response(
                {
                    "success": False,
                    "data": None,
                    "error": {
                        "code": "device_already_registered",
                        "message": (
                            "Bu kompyuter uchun faol qurilma tokeni mavjud"
                            if same_machine
                            else "Bu kompyuter boshqa mashinaga biriktirilgan. "
                            "Administratorga murojaat qiling."
                        ),
                        "details": (
                            {"device_id": existing.device_id} if same_machine else None
                        ),
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        if data.get("info_pc"):
            Computer.objects.filter(pk=computer.pk).update(info_pc=data["info_pc"])

        device = services.register_device(
            computer=computer,
            hardware_fingerprint=data.get("hardware_fingerprint", ""),
            app_version=data.get("app_version", ""),
            app_hash=data.get("app_hash", ""),
            reported_public_ip=reported_ip or None,
        )
        return Response(
            {
                "device_id": device.device_id,
                "status": device.status,
                "computer": {
                    "inventory_code": computer.inventory_code,
                    "zone": computer.zone.name,
                },
                "detail": "Qurilma ro'yxatga olindi, admin tasdig'ini kuting",
            },
            status=status.HTTP_201_CREATED,
        )
