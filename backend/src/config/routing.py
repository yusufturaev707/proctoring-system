"""WebSocket marshrutlari."""

from django.urls import path

from apps.proctoring.consumers import ClientConsumer, MonitorConsumer

websocket_urlpatterns = [
    # Proktor / admin dashboard (faqat kuzatadi + buyruq yuboradi)
    path("ws/monitor/", MonitorConsumer.as_asgi()),
    # PyQt6 desktop client (ikki tomonlama: heartbeat + buyruqlar)
    path("ws/client/", ClientConsumer.as_asgi()),
]
