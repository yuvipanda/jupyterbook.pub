#!/bin/bash
set -euo pipefail
# Dokku entrypoint, to make life easier

CONFIG_FILE="deploy_config/{$CONFIG_FILE:-jupyterbook.py}"

exec python3 -m jupyterbook_pub.app \
    --JupyterBookPubApp.debug=true \
    --JupyterBookPubApp.port=${PORT} \
    --JupyterBookPubApp.built_sites_root=/opt/persistent/sites \
    --JupyterBookPubApp.repo_checkout_root=/opt/persistent/repos \
    -f ${CONFIG_FILE}
