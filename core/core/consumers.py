from channels.generic.websocket import AsyncWebsocketConsumer
import json

# Rename class to match admin-seat-map use-case
class AdminSeatMapConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("admin_seat_map", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("admin_seat_map", self.channel_name)

    async def send_pending_seat(self, event):
        await self.send(text_data=json.dumps({
            "type": event["type"],
            "seat_type": event["seat_type"],
            "seat_id": event["seat_id"]
        }))

