#!/bin/bash
# `docker compose exec acp-ant account.sh ...` runs as root by default; the gateway runs as acpant (uid 1000),
# so switch first, otherwise new account files would belong to root and the gateway could not read them.
if [ "$(id -u)" = 0 ]; then
  exec setpriv --reuid=1000 --regid=1000 --init-groups env HOME=/home/acpant /usr/local/lib/acp-ant/account.sh "$@"
fi
exec /usr/local/lib/acp-ant/account.sh "$@"
