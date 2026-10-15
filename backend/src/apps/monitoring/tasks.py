from celery import shared_task

from apps.monitoring import services


@shared_task(name="monitoring.sample_system", ignore_result=True)
def sample_system():
    """
    Server holati tarixiga bitta nuqta (30 s, `config/celery.py`).

    Jonli ko'rsatkichlarni panel o'zi so'raydi; bu vazifa faqat grafik
    tarixi, kunlik disk o'sishi va storage hajmi uchun. Ishlamasa
    sahifa baribir ishlaydi va buni o'zi aytadi (`history_stale`).
    """
    services.sample_history()
