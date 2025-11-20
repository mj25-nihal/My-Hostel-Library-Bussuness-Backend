from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # WebSocket route for admin notifications
    re_path(r'ws/admin/notifications/$', consumers.AdminSeatMapConsumer.as_asgi()),
]
