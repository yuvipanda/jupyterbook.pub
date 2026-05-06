#!/bin/bash
set -euo pipefail
# Dokku entrypoint, to make life easier

CONFIG_FILE="deploy_config/${CONFIG_FILE:-jupyterbook.py}"

exec python3 -m jupyterbook_pub.app \
    --debug \
    --port=${PORT} \
    --storage=/opt/persistent/ \
    -f ${CONFIG_FILE}
