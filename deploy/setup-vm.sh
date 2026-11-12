#!/usr/bin/env bash
# =====================================================================
#  CacaoSmart IoT - Arranque en la VM (ejecutar dentro del repositorio clonado)
#  - Si no existe .env, lo crea desde .env.example con claves aleatorias.
#  - Construye y levanta todos los servicios. Caddy obtiene el certificado TLS solo.
#  Uso: AZURE_MAPS_KEY=xxxx PUBLIC_URL=https://cacaosmart-iot.northcentralus.cloudapp.azure.com bash deploy/setup-vm.sh
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "==> Generando .env con secretos aleatorios"
  cp .env.example .env
  rnd() { openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24; }
  for k in MQTT_DEVICE_PASS MQTT_SERVICE_PASS MQTT_OPERATOR_PASS INFLUX_ADMIN_PASS GRAFANA_ADMIN_PASS API_TOKEN NODERED_ADMIN_PASS; do
    sed -i "s|^$k=.*|$k=$(rnd)|" .env
  done
  sed -i "s|^INFLUX_TOKEN=.*|INFLUX_TOKEN=$(openssl rand -hex 32)|" .env
  [ -n "${AZURE_MAPS_KEY:-}" ] && sed -i "s|^AZURE_MAPS_KEY=.*|AZURE_MAPS_KEY=$AZURE_MAPS_KEY|" .env
  [ -n "${PUBLIC_URL:-}" ] && sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=$PUBLIC_URL|" .env
  echo "    Guarde las claves de .env en un lugar seguro (operador, Grafana, API_TOKEN)."
fi
grep -q '^PUBLIC_URL=https://' .env || echo "AVISO: PUBLIC_URL no es https://... -> no habrá certificado TLS"

echo "==> Construyendo y levantando servicios"
docker compose pull --quiet
docker compose up -d --build
docker compose ps
echo
echo "Panel:   $(grep ^PUBLIC_URL .env | cut -d= -f2)/"
echo "Grafana: $(grep ^PUBLIC_URL .env | cut -d= -f2)/grafana/"
echo "Sin ESP32 físicos todavía? -> docker compose --profile emulador up -d"
