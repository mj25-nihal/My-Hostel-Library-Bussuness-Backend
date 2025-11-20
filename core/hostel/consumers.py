import json
from channels.generic.websocket import AsyncWebsocketConsumer

class SeatUpdateConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = 'live_seat_updates'

        # Join group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # Leave group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # Optional: handle data sent from frontend if needed
        pass

    async def send_seat_update(self, event):
        await self.send(text_data=json.dumps(event["data"]))
