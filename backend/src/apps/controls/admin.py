from django.contrib import admin

from apps.controls.models import (
    AllowedPublicIp,
    CocoObject,
    CocoObjectGroup,
    EventRiskWeight,
    HotKeyboardKey,
    ModelVersion,
    ProctoringPolicy,
    RdpObject,
    Setting,
)


@admin.register(Setting)
class SettingAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "faceid_interval", "is_screenshot_upload")
    list_filter = ("is_active",)
    filter_horizontal = ("detect_classes", "rdp_objects", "hotkeys")
    # Panel sahifasi (`Settings.jsx`) bilan BIR XIL guruhlash: bitta
    # maydonni ikki joyda ikki xil bo'limda qidirish administratorni
    # adashtirardi. Mashinaga xos qiymatlar (server manzili, kamera
    # indeksi, GPU) bu yerda YO'Q - ular client `.env` ida
    # (`CLAUDE.md`: "Client sozlamalari: .env va panel").
    fieldsets = (
        (None, {"fields": ("name", "is_active")}),
        (
            "FaceID",
            {
                "fields": (
                    "is_faceid_student", "is_faceid_exam",
                    "faceid_min_score_student", "faceid_min_score_exam",
                    "faceid_interval", "faceid_max_fail", "warning_timeout",
                    "faceid_audit_rate",
                )
            },
        ),
        (
            "FaceID: kirish tekshiruvi oqimi",
            {
                "fields": (
                    "faceid_guide_seconds", "faceid_match_streak",
                    "faceid_fail_streak", "faceid_fail_min_seconds",
                )
            },
        ),
        (
            "FaceID: test davomida yuz uzoqda",
            {"fields": ("faceid_far_warn_s", "faceid_far_unverified_s")},
        ),
        (
            "Skrinshot",
            {
                "fields": (
                    "is_screenshot_upload", "screenshot_quality", "screenshot_max_width",
                    "is_screenshot_camera_overlay", "screenshot_pip_percent",
                )
            },
        ),
        (
            "Ekran yozuvi",
            {
                "fields": (
                    "is_screen_record", "screen_record_fps", "screen_record_width",
                    "screen_record_pip_percent",
                )
            },
        ),
        ("Qurilma tekshiruvi", {"fields": ("is_detect_monitor", "is_detect_camera")}),
        (
            "Obyekt aniqlash (YOLO)",
            {
                "fields": (
                    "is_enable_detect", "detect_model", "detect_confidence",
                    "detect_frame_skip", "detect_classes",
                )
            },
        ),
        (
            "Himoya",
            {
                "fields": (
                    "is_enable_rdp_detect", "rdp_objects", "is_threat_block_exam",
                    "hotkeys", "is_enable_check_tp",
                )
            },
        ),
        (
            "Tarmoq",
            {"fields": ("heartbeat_interval", "event_batch_interval", "offline_buffer_size")},
        ),
        # Fieldset'siz admin buni ko'rsatardi va o'chirilgan profilni
        # tiklashning yagona yo'li shu - yashirib qo'ymaymiz.
        ("Tizim", {"fields": ("deleted_at",), "classes": ("collapse",)}),
    )


@admin.register(AllowedPublicIp)
class AllowedPublicIpAdmin(admin.ModelAdmin):
    list_display = ("ip_address", "zone", "name", "is_active")
    list_filter = ("is_active", "zone")
    search_fields = ("ip_address", "name")


@admin.register(ProctoringPolicy)
class ProctoringPolicyAdmin(admin.ModelAdmin):
    list_display = ("setting", "is_enabled", "camera_count", "primary_required", "gpu_profile_override")
    list_filter = ("is_enabled", "camera_count", "gpu_profile_override")
    search_fields = ("setting__name",)
    list_select_related = ("setting",)
    fieldsets = (
        (None, {"fields": ("setting", "is_enabled")}),
        (
            "Kamera",
            {
                "fields": (
                    "camera_count", "primary_camera_kind", "secondary_camera_kind",
                    "primary_required", "secondary_required", "allow_virtual_camera",
                    "min_fps", "min_width", "min_height",
                    "camera_lost_grace_s", "camera_lost_action",
                )
            },
        ),
        (
            "AI modullari",
            {
                "fields": (
                    "enable_identity", "enable_objects", "enable_pose",
                    "enable_gaze", "enable_tracking",
                    "identity_fps", "object_fps", "pose_fps", "gaze_fps",
                    "gpu_profile_override",
                )
            },
        ),
        (
            "Temporal chegaralar",
            {
                "fields": (
                    "no_face_warn_s", "no_face_suspicious_s",
                    "gaze_away_warn_s", "gaze_away_suspicious_s",
                    "object_min_frames", "object_min_conf", "object_min_duration_ms",
                    "fusion_window_ms",
                )
            },
        ),
        (
            "Xavf balli",
            {
                "fields": (
                    "risk_decay_per_min", "risk_event_cooldown_s",
                    "threshold_low", "threshold_medium", "threshold_high",
                )
            },
        ),
        (
            "Dalil",
            {
                "fields": (
                    "evidence_enabled", "evidence_clip_seconds", "evidence_min_severity",
                    "evidence_clip_retention_days", "evidence_frame_retention_days",
                )
            },
        ),
    )


@admin.register(EventRiskWeight)
class EventRiskWeightAdmin(admin.ModelAdmin):
    list_display = ("event_type", "weight", "cooldown_s", "is_active")
    list_filter = ("is_active",)
    search_fields = ("event_type",)
