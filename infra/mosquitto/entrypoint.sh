#!/bin/sh
# Genera el archivo de claves a partir de las variables de entorno (.env)
set -e
PW=/mosquitto/data/passwd
rm -f "$PW"; touch "$PW"; chmod 0700 "$PW"
mosquitto_passwd -b "$PW" "$MQTT_SERVICE_USER"  "$MQTT_SERVICE_PASS"
mosquitto_passwd -b "$PW" "$MQTT_DEVICE_USER"   "$MQTT_DEVICE_PASS"
mosquitto_passwd -b "$PW" "$MQTT_VIEWER_USER"   "$MQTT_VIEWER_PASS"
mosquitto_passwd -b "$PW" "$MQTT_OPERATOR_USER" "$MQTT_OPERATOR_PASS"
cp /mosquitto/config/acl /mosquitto/data/acl
chown mosquitto:mosquitto "$PW" /mosquitto/data/acl
chmod 0700 /mosquitto/data/acl
echo "[cacaosmart] usuarios MQTT generados"
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
