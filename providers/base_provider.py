# providers/base_provider.py
import logging
import json
from abc import ABC, abstractmethod
from datetime import datetime


class BaseProvider(ABC):

    @abstractmethod
    def process_status_call(self, device_id):
        """Executes the status API call"""
        pass

    @abstractmethod
    def process_command_call(self, device_id, payload):
        """Executes the command API call"""
        pass

    @abstractmethod
    def handle_webhook(self, path, data):
        """Handles incoming status reports from Webhooks (HTTP POST)"""
        pass

    def poll_status(self):
        self.logger.info("Polling status for all valid devices...")
        for devicename in self.devices_by_name.keys():
            topic_cmnd = f"{self.mqtt_base_topic}{devicename}/cmnd"
            self.mqtt_client.publish(topic_cmnd, json.dumps({"command": "status"}))

    def __init__(self, config, mqtt_base_topic, mqtt_client, version):
        self.name = self.__class__.__name__
        self.logger = logging.getLogger(f"generic-api2mqtt.providers.{self.name}")
        self.version = version
        self.config = config
        self.mqtt_client = mqtt_client
        self.api_baseurl = config.get("API_BASEURL")
        self.token = config.get("TOKEN")
        self.mqtt_base_topic = mqtt_base_topic
        self.devices_by_name = config.get("DEVICES", {})
        self.devices_by_id = {v: k for k, v in self.devices_by_name.items()}
        self.valid_commands = config.get("VALID_COMMANDS", {})
        self.polling_interval_sec = config.get("POLLING_INTERVAL_SEC")
        self.print_config_info()
        self.logger.info(f"{self.name} provider initialized")

    def print_config_info(self):
        self.logger.info(f"PROVIDER {self.name} VERSION {self.version}")
        self.logger.debug(f"API_BASEURL: {self.api_baseurl}")
        self.logger.debug(f"TOKEN: {'*' * 8 if self.token else 'None'}")
        self.logger.debug(f"MQTT_BASE_TOPIC: {self.mqtt_base_topic}")
        self.logger.debug(f"DEVICES: {self.devices_by_name}")
        self.logger.debug(f"VALID COMMANDS: {self.valid_commands}")
        self.logger.debug(f"POLLING_INTERVAL_SEC: {self.polling_interval_sec}")

    def generate_mqtt_response_message(self, status, result, error):
        return json.dumps({
            "timestamp": datetime.now().isoformat(sep=" ", timespec="milliseconds"),
            "status": status,
            "result": result,
            "error": error
        })

    def generate_mqtt_success_message(self, result):
        return self.generate_mqtt_response_message("SUCCESS", result, None)

    def generate_mqtt_error_message(self, error):
        return self.generate_mqtt_response_message("ERROR", None, error)

    def handle_mqtt_message(self, msg):
        response_topic = None
        try:
            topic = msg.topic
            payload = msg.payload
            if not topic.startswith(self.mqtt_base_topic) or not topic.endswith("/cmnd"):
                return

            response_topic = f"{topic[0:-4]}response"

            device_name = topic.split('/')[-2]
            device_id = self.devices_by_name.get(device_name)
            if not device_id:
                raise ValueError(f"Device '{device_name}' not found in DEVICES configuration")

            device_type = device_name.split('.')[0]
            try:
                mqtt_payload = json.loads(payload.decode('utf-8').strip())
            except json.JSONDecodeError:
                raise ValueError(f"Invalid payload for {device_name}. JSON format required.")

            command_verb = mqtt_payload.get("command")
            mqtt_value = mqtt_payload.get("value")
            if not command_verb:
                raise ValueError("Missing 'command' key in MQTT payload.")

            if command_verb == "status":
                res = self.process_status_call(device_id)
            else:
                valid_commands = self.valid_commands.get(device_type, {})
                command_template = valid_commands.get(command_verb)
                if not command_template:
                    raise ValueError(f"Command '{command_verb}' is not supported for family '{device_type}'.")

                template_str = json.dumps(command_template)
                if "%value%" in template_str:
                    if mqtt_value is None:
                        raise ValueError(f"Command '{command_verb}' requires a 'value', but none was provided.")
                    if isinstance(mqtt_value, str):
                        cleaned_value = mqtt_value.strip()
                        try:
                            mqtt_value = int(cleaned_value)
                        except ValueError:
                            try:
                                mqtt_value = float(cleaned_value)
                            except ValueError:
                                pass
                    if isinstance(mqtt_value, (int, float)):
                        template_str = template_str.replace('"%value%"', str(mqtt_value))
                    else:
                        template_str = template_str.replace('%value%', str(mqtt_value))
                self.logger.info(f"template_str {template_str}")
                commandPayload = json.loads(template_str)

                self.logger.info(f"Executing dynamic command '{command_verb}' on {device_name} ({device_id})")
                self.logger.debug(f"Payload sent: {commandPayload}")

                res = self.process_command_call(device_id, commandPayload)

            if res is not None:
                if res.status_code == 200:
                    self.mqtt_client.publish(response_topic, self.generate_mqtt_success_message(res.json()))
                else:
                    raise RuntimeError(f"API error [{res.status_code}]: {json.loads(res.text)}")
            else:
                raise RuntimeError("No response received from API (Timeout or network error)")

        except Exception as e:
            self.logger.exception(f"Error handling MQTT message: {e}")
            if response_topic:
                try:
                    self.mqtt_client.publish(response_topic, self.generate_mqtt_error_message(str(e)))
                except Exception as mqtt_err:
                    self.logger.error(f"Failed to send error payload via MQTT: {mqtt_err}")

    def get_subscriptions(self):
        return [f"{self.mqtt_base_topic}{name}/cmnd" for name in self.devices_by_name.keys()]
