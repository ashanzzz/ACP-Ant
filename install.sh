#!/bin/bash
# ACP-Ant 一键安装（Linux，x86_64 / arm64；需要 python3、curl，装 systemd 服务需要 sudo）
#   ./install.sh                 安装到 /opt/acp-ant，并装成 systemd 服务 acp-ant（只监听 127.0.0.1:8095）
#   ./install.sh --no-systemd    只装文件，不装服务（自己用 uvicorn 启动）
# 可用环境变量：AGY_ROOT（安装目录）、AGY_PORT（端口，默认 8095）、AGY_HOST（默认 127.0.0.1）、
#               AGY_BIN（已经装好的 agy 路径，设了就不再下载官方 CLI）
set -euo pipefail
ROOT=${AGY_ROOT:-/opt/acp-ant}
PORT=${AGY_PORT:-8095}
HOST=${AGY_HOST:-127.0.0.1}
SRC=$(cd "$(dirname "$0")" && pwd)
RUN_USER=${SUDO_USER:-$(id -un)}
SYSTEMD=1
[ "${1:-}" = "--no-systemd" ] && SYSTEMD=0

say() { echo "==> $*"; }
die() { echo "错误：$*" >&2; exit 1; }
SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo"

command -v python3 >/dev/null || die "需要 python3"
command -v curl >/dev/null || die "需要 curl"
python3 -c "import venv" 2>/dev/null || die "需要 python3-venv（Ubuntu / Debian：sudo apt install python3-venv）"

say "安装目录 $ROOT（运行用户 $RUN_USER）"
if [ ! -d "$ROOT" ]; then
  if mkdir -p "$ROOT" 2>/dev/null; then :; else $SUDO mkdir -p "$ROOT" && $SUDO chown "$RUN_USER" "$ROOT"; fi
fi
mkdir -p "$ROOT/bin" "$ROOT/accounts"
chmod 700 "$ROOT/accounts"

if [ -n "${AGY_BIN:-}" ]; then
  [ -x "$AGY_BIN" ] || die "AGY_BIN=$AGY_BIN 不存在或不能执行"
  say "使用已有的 agy：$AGY_BIN"
elif [ -x "$ROOT/bin/agy" ]; then
  say "官方 agy 已安装：$("$ROOT/bin/agy" --version 2>/dev/null | head -1)"
else
  say "下载并安装官方 Antigravity CLI（agy）到 $ROOT/bin"
  tmp=$(mktemp)
  curl -fsSL https://antigravity.google/cli/install.sh -o "$tmp"
  bash "$tmp" --dir "$ROOT/bin"
  rm -f "$tmp"
  [ -x "$ROOT/bin/agy" ] || die "agy 安装失败"
fi

say "Python 虚拟环境和依赖"
[ -x "$ROOT/venv/bin/python" ] || python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install -q --upgrade pip
"$ROOT/venv/bin/pip" install -q -r "$SRC/requirements.txt"

say "复制程序文件"
install -m 644 "$SRC/acp_ant.py" "$SRC/acp_panel.py" "$SRC/panel.html" "$ROOT/"
sed -e "s#^ROOT=\${AGY_ROOT:-/opt/acp-ant}#ROOT=\${AGY_ROOT:-$ROOT}#" \
    -e "s#^AGY=\${AGY_BIN:-\$ROOT/bin/agy}#AGY=\${AGY_BIN:-${AGY_BIN:-$ROOT/bin/agy}}#" \
    "$SRC/scripts/account.sh" > "$ROOT/account.sh"
chmod 755 "$ROOT/account.sh"
install -m 644 "$SRC/scripts/smoke_test.py" "$SRC/scripts/agent_test.py" "$SRC/scripts/acp_probe.py" "$ROOT/"

if [ ! -f "$ROOT/gateway.env" ]; then
  say "生成网关密钥（写在 $ROOT/gateway.env，权限 600）"
  ( umask 077
    {
      echo "AGY_GATEWAY_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
      echo "AGY_ROOT=$ROOT"
      [ -n "${AGY_BIN:-}" ] && echo "AGY_BIN=$AGY_BIN"
      echo "# 每个账号同时跑几个请求、单次请求超时（秒）、本地会话记录保留几小时："
      echo "AGY_PER_ACCOUNT=3"
      echo "AGY_REQUEST_TIMEOUT=290"
      echo "AGY_KEEP_HOURS=6"
    } > "$ROOT/gateway.env" )
else
  say "保留已有的 $ROOT/gateway.env"
fi

if [ "$SYSTEMD" = 1 ]; then
  command -v systemctl >/dev/null || die "没有 systemd；用 --no-systemd 安装后自己启动"
  say "安装 systemd 服务 acp-ant（$HOST:$PORT）"
  sed -e "s#@USER@#$RUN_USER#g" -e "s#@ROOT@#$ROOT#g" -e "s#@PORT@#$PORT#g" -e "s#@HOST@#$HOST#g" \
    "$SRC/deploy/acp-ant.service" | $SUDO tee /etc/systemd/system/acp-ant.service >/dev/null
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now acp-ant
  sleep 2
  $SUDO systemctl restart acp-ant   # 已经在运行（升级）时也要重启才会用上新代码
  sleep 3
  systemctl is-active acp-ant >/dev/null && say "服务已启动" || echo "服务没起来，看日志：journalctl -u acp-ant -n 50"
else
  say "没装服务。手动启动："
  echo "  set -a; . $ROOT/gateway.env; set +a; $ROOT/venv/bin/uvicorn acp_ant:app --app-dir $ROOT --host $HOST --port $PORT"
fi

cat <<EOF

安装完成。
网页控制面板：http://$HOST:$PORT/   （装在服务器上时，用反向代理绑定域名后用 https://你的域名/ 打开）
  第一次登录的初始密码保存在 $ROOT/panel-initial-password.txt（查看：cat $ROOT/panel-initial-password.txt），
  在面板「设置」里改成自己的密码后，这个文件会自动删除。
在面板里就能添加账号、登录 Google、换代理、看额度、开关账号；也可以用命令行：
  $ROOT/account.sh add g1
查看账号：  $ROOT/account.sh list
网关密钥：  grep AGY_GATEWAY_KEY $ROOT/gateway.env
接口地址：  http://$HOST:$PORT/v1   （OpenAI 兼容，Bearer 用上面的密钥）
EOF
