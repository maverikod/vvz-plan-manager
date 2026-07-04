#!/bin/sh
# Container health probe for the plan_manager adapter.
#
# The probe must speak the same protocol the adapter serves, which is taken
# from server.protocol in the mounted configuration (/etc/planmgr/config.json):
#   - mtls : HTTPS with the mounted client certificate presented
#   - https: HTTPS, accepting the self-signed server certificate (-k)
#   - http : plain HTTP
# Any failure yields a non-zero exit so Docker marks the container unhealthy.
set -eu

CONFIG="${PLANMGR_CONFIG:-/etc/planmgr/config.json}"
PORT="${PLANMGR_HEALTH_PORT:-8080}"

protocol="$(python -c "import json,sys; print(json.load(open('${CONFIG}'))['server'].get('protocol','http'))" 2>/dev/null || echo http)"

case "${protocol}" in
    mtls)
        exec curl -fsSk \
            --cert /etc/planmgr/secrets/client.crt \
            --key /etc/planmgr/secrets/client.key \
            "https://localhost:${PORT}/health"
        ;;
    https)
        exec curl -fsSk "https://localhost:${PORT}/health"
        ;;
    *)
        exec curl -fsS "http://localhost:${PORT}/health"
        ;;
esac
