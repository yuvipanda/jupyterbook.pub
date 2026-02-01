#!/bin/bash
set -euo pipefail
# Dokku entrypoint, to make life easier

exec python3 -m jupyterbook_pub.app \
    --JupyterBookPubApp.port=${PORT} \
    --JupyterBookPubApp.built_sites_root=/opt/persistent/sites \
    --JupyterBookPubApp.built_sites_root=/opt/persistent/repos