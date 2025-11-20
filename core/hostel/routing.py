from django.urls import re_path
from .consumers import SeatUpdateConsumer

websocket_urlpatterns = [
    re_path(r'ws/seat-updates/$', SeatUpdateConsumer.as_asgi()),
]
