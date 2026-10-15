from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.monitoring"
    label = "monitoring"

    def ready(self):
        # Celery signallari har jarayonda ulanadi, lekin faqat ishchida
        # ishga tushadi (vazifa bajarilganda). Qaysi davriy vazifa qachon
        # oxirgi marta bajarilgani — beat va ishchilar tirikligining eng
        # aniq belgisi (`celery_health.py`).
        from apps.monitoring import celery_health

        celery_health.connect_signals()
