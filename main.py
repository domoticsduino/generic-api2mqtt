# main.py
import json
import time
import threading
import logging
import logging.config
import paho.mqtt.client as mqtt
from flask import Flask, request, jsonify

with open('logging.json', 'r') as f:
    logConfig = json.load(f)
    logging.config.dictConfig(logConfig)

from providers.switchbot import SwitchBotProvider
from providers.smartthings import SmartThingsProvider

_VERSION = "1.0 beta"
_APPNAME = "generic-api2mqtt"

logger = logging.getLogger("generic-api2mqtt")

with open("config.json", "r") as f:
    CONFIG = json.load(f)

app = Flask(__name__)
providers = {}


@app.route('/webhook/<provider_name>', methods=['POST'])
def global_webhook(provider_name):
    if provider_name in providers:
        data = request.get_json()
        logger.debug(f"Webhook received for {provider_name}: {data}")
        res, status_code = providers[provider_name].handle_webhook(request.path, data)
        return jsonify(res), status_code
    return jsonify({"error": "Provider not found"}), 404


def on_connect(client, userdata, flags, rc, properties=None):
    logger.info("Connected to MQTT Broker")
    for name, provider in providers.items():
        for topic in provider.get_subscriptions():
            client.subscribe(topic)
            logger.info(f"Subscribed to {name} topic: {topic}")


def on_message(client, userdata, msg):
    for provider in providers.values():
        provider.handle_mqtt_message(msg)


def provider_polling_loop(name, provider, interval):
    logger.info(f"Started polling thread for '{name}' with interval: {interval}s")
    while True:
        try:
            logger.debug(f"Executing periodic polling for {name}...")
            provider.poll_status()
        except Exception as e:
            logger.exception(f"Polling error on {name}: {e}")
        time.sleep(interval)


def print_config_info():
    logger.info(f"START {_APPNAME} version {_VERSION}")
    logger.debug(f"MQTT_BROKER: {CONFIG['MQTT']['BROKER']}")
    logger.debug(f"MQTT_PORT: {CONFIG['MQTT']['PORT']}")
    logger.debug(f"MQTT_USERNAME: {CONFIG['MQTT']['USERNAME']}")
    logger.debug(f"MQTT_PASSWORD: {'*' * 8 if CONFIG['MQTT']['PASSWORD'] else 'None'}")
    logger.debug(f"MQTT_CLIENT_ID: {CONFIG['MQTT']['CLIENT_ID']}")
    logger.debug(f"WEBHOOK_HTTP_PORT: {CONFIG['WEBHOOK']['HTTP_PORT']}")


if __name__ == "__main__":

    print_config_info()

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, CONFIG["MQTT"]["CLIENT_ID"])
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    if CONFIG["MQTT"]["USERNAME"] and CONFIG["MQTT"]["PASSWORD"]:
        mqtt_client.username_pw_set(CONFIG["MQTT"]["USERNAME"], CONFIG["MQTT"]["PASSWORD"])

    providers["switchbot"] = SwitchBotProvider(CONFIG["SWITCHBOT"], CONFIG["MQTT"]["BASE_TOPIC"], mqtt_client)
    providers["smartthings"] = SmartThingsProvider(CONFIG["SMARTTHINGS"], CONFIG["MQTT"]["BASE_TOPIC"], mqtt_client)

    try:
        mqtt_client.connect(CONFIG["MQTT"]["BROKER"], int(CONFIG["MQTT"]["PORT"]), 60)
    except Exception as e:
        logger.exception(f"MQTT connection failed: {e}")
        exit(1)

    http_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(CONFIG["WEBHOOK"]["HTTP_PORT"])))
    http_thread.daemon = True
    http_thread.start()

    for name, provider_instance in providers.items():
        config_section = CONFIG.get(name.upper(), {})
        polling_interval = config_section.get("POLLING_INTERVAL_SEC", 0)

        if polling_interval > 0:
            poll_thread = threading.Thread(
                target=provider_polling_loop,
                args=(name, provider_instance, polling_interval),
                name=f"PollThread-{name}"
            )
            poll_thread.daemon = True
            poll_thread.start()
        else:
            logger.warning(f"Polling disabled or not configured for provider: '{name}'")

    logger.info(f"{_APPNAME} successfully started. Listening on MQTT and HTTP.")
    mqtt_client.loop_forever()
