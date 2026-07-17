# providers/smartthings.py
import json
from providers.base_provider import BaseProvider
from http_utils import http_get, http_post

_VERSION = "1.0 beta"
_PROVIDER = "smartthings"


class SmartThingsProvider(BaseProvider):

    def print_config_info(self):
        super().print_config_info()

    def process_status_call(self, device_id):
        return http_get(f"{self.api_baseurl}devices/{device_id}", self.generate_headers())

    def process_command_call(self, device_id, payload):
        return http_post(f"{self.api_baseurl}devices/{device_id}/commands", payload, self.generate_headers())

    def generate_headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def handle_webhook(self, path, data):

        if data.get("lifecycle") == "CONFIRMATION":
            confirmation_url = data["confirmationData"]["confirmationUrl"]
            http_get(confirmation_url, {})
            return {"targetUrlVerificationResponse": "success"}, 200

        elif data.get("lifecycle") == "CONFIGURATION":
            if data.get("configurationData").get("phase") == "INITIALIZE":
                return {"configurationData": {"initialize": {"name": "Generic2MQTT Bridge", "description": "Send events to Bridge", "id": "Generic2MQTT_Bridge", "permissions": ["r:devices:*"], "firstPageId": "1"}}}, 200
            elif data.get("configurationData").get("phase") == "PAGE":
                return {"configurationData": {"page": {"pageId": "1", "name": "Choose your devices", "complete": True, "sections": [{"name": "Device to monitor", "settings": [{"id": "myDevices", "name": "Devices", "description": "Choose your SmartThings devices", "type": "DEVICE", "multiple": True, "required": True, "capabilities": ["ocf"], "permissions": ["r"]}]}]}}}, 200

        elif data.get("lifecycle") == "EVENT":
            events = data.get("eventData", {}).get("events", [])
            for event in events:
                if event.get("eventType") == "DEVICE_EVENT":
                    device_event = event.get("deviceEvent", {})
                    device_id = device_event.get("deviceId")
                    device_name = self.devices_by_id.get(device_id)
                    if device_name:
                        topic = f"{self.mqtt_base_topic}{device_name}/event"
                        self.logger.info(f"Sending event to MQTT topic {topic}")
                        self.mqtt_client.publish(topic, json.dumps(event), qos=1, retain=True)
            return {"eventData": {}}, 200

        elif data.get("lifecycle") == "INSTALL":
            return {"installData": {}}, 200

        elif data.get("lifecycle") == "UPDATE":
            return {"updateData": {}}, 200

        elif data.get("lifecycle") == "UNINSTALL":
            return {"uninstallData": {}}, 200

        return {"status": "IGNORED"}, 200

    def __init__(self, config, mqtt_base_topic, mqtt_client):
        super().__init__(config, f"{mqtt_base_topic}/{_PROVIDER}/", mqtt_client, _VERSION)
