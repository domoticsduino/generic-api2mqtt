# providers/switchbot.py
import json
import time
import uuid
import hmac
import hashlib
import base64
from providers.base_provider import BaseProvider
from http_utils import http_get, http_post

_VERSION = "1.0 beta"
_PROVIDER = "switchbot"


class SwitchBotProvider(BaseProvider):

    def print_config_info(self):
        super().print_config_info()
        self.logger.debug(f"SECRET: {'*' * 8 if self.secret else 'None'}")

    def process_status_call(self, device_id):
        return http_get(f"{self.api_baseurl}devices/{device_id}/status", self.generate_headers())

    def process_command_call(self, device_id, payload):
        return http_post(f"{self.api_baseurl}devices/{device_id}/commands", payload, self.generate_headers())

    def generate_headers(self):
        t = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        string_to_sign = self.token + t + nonce
        sign = base64.b64encode(
            hmac.new(self.secret.encode(), msg=string_to_sign.encode(), digestmod=hashlib.sha256).digest()
            ).decode()
        return {
            "Authorization": self.token,
            "sign": sign,
            "t": t,
            "nonce": nonce,
            "Content-Type": "application/json; charset=utf8"
        }

    def handle_webhook(self, path, data):
        if data.get("eventType") == "changeReport":
            context = data.get("context", {})
            device_id = context.get("deviceMac")
            if device_id in self.devices_by_id:
                device_name = self.devices_by_id.get(device_id)
                topic = f"{self.mqtt_base_topic}{device_name}/event"
                self.logger.info(f"Sending event to MQTT topic {topic}")
                self.mqtt_client.publish(topic, json.dumps(data))
                return {"status": "ok"}, 200
        return {"error": "Invalid payload"}, 400

    def __init__(self, config, mqtt_base_topic, mqtt_client):
        self.secret = config.get("SECRET")
        super().__init__(config, f"{mqtt_base_topic}/{_PROVIDER}/", mqtt_client, _VERSION)
