#!/usr/bin/env bash
# =====================================================================
#  CacaoSmart IoT - Crea la infraestructura en Microsoft Azure (Azure CLI)
#  Requisitos: az login (cuenta Azure for Students sirve), bash (Cloud Shell, WSL o Git Bash)
#
#  Uso:   DNS=cacaosmart-iot LOC=northcentralus bash deploy/azure-deploy.sh   (Azure for Students sólo permite: northcentralus, westus3, mexicocentral, centralus, chilecentral)
#  Crea:  grupo de recursos + VM Ubuntu 24.04 B2s + IP pública con DNS propio + reglas NSG 80/443/1883
#  URL:   https://<DNS>.<LOC>.cloudapp.azure.com
# =====================================================================
set -euo pipefail
RG=${RG:-cacaosmart-rg}
LOC=${LOC:-northcentralus}
VM=${VM:-cacaosmart-vm}
DNS=${DNS:-cacaosmart-iot}
SIZE=${SIZE:-Standard_B2as_v2}
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v cygpath >/dev/null && HERE="$(cygpath -m "$HERE")"   # Git Bash en Windows: az necesita ruta Windows

echo "==> Grupo de recursos $RG en $LOC"
az group create -n "$RG" -l "$LOC" -o none

echo "==> Máquina virtual $VM ($SIZE, Ubuntu 24.04) con Docker vía cloud-init"
az vm create -g "$RG" -n "$VM" \
  --image Canonical:ubuntu-24_04-lts:server:latest \
  --size "$SIZE" \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard --public-ip-address-dns-name "$DNS" \
  --os-disk-size-gb 32 \
  --custom-data "$HERE/cloud-init.yaml" -o none

echo "==> Reglas de red: 80/443 (HTTPS + Let's Encrypt) y 1883 (MQTT de los ESP32)"
az vm open-port -g "$RG" -n "$VM" --port 80,443,1883 --priority 1010 -o none

FQDN="$DNS.$LOC.cloudapp.azure.com"
echo
echo "Listo. Siguientes pasos:"
echo "  1) scp .env azureuser@$FQDN:~/            (con PUBLIC_URL=https://$FQDN)"
echo "  2) ssh azureuser@$FQDN"
echo "  3) git clone <su-repo> cacaosmart-iot && cd cacaosmart-iot && mv ~/.env . && bash deploy/setup-vm.sh"
echo "  URL pública: https://$FQDN"
