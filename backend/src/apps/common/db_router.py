from django.conf import settings


class ReadReplicaRouter:
    """
    O'qishni replica'ga, yozishni primary'ga yo'naltiradi.

    Ehtiyot: replikatsiya lag'i (~100ms–2s) sababli "yozdim va darhol o'qidim"
    stsenariysi replica'da topilmasligi mumkin. Shunday joylarda aniq
    `.using("default")` yozing (masalan sessiya yaratilgandan keyingi o'qish).
    """

    #: Bu app'lar har doim primary'dan o'qiydi — ular yozishga juda yaqin.
    WRITE_CRITICAL_APPS = {"proctoring", "devices", "sessions", "token_blacklist"}

    def _has_replica(self) -> bool:
        return "replica" in settings.DATABASES

    def db_for_read(self, model, **hints):
        if not self._has_replica():
            return None
        if model._meta.app_label in self.WRITE_CRITICAL_APPS:
            return "default"
        return "replica"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        # Ikkala ulanish ham bir xil fizik klaster — relation'lar ruxsat etiladi.
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"
