#!/bin/bash
# ACP-Ant 一键安装 / 升级（Linux，x86_64 / arm64；需要 python3、curl）
#   ./install.sh                 装到 /opt/acp-ant，装成系统服务 acp-ant（需要 sudo；只监听 127.0.0.1:8095）
#   ./install.sh --user          不用 sudo：装到 ~/acp-ant，装成当前用户的服务（systemctl --user）
#   ./install.sh --no-systemd    只装文件，不装服务（自己用 uvicorn 启动）
#   ./install.sh --update        只更新程序文件和依赖（面板「立即更新」用；不动服务和配置）
# 再次运行就是升级：保留 gateway.env、账号、面板密码和统计。
# 可用环境变量：AGY_ROOT（安装目录）、AGY_PORT（端口，默认 8095）、AGY_HOST（默认 127.0.0.1）、
#               AGY_BIN（已经装好的 agy 路径，设了就不再下载官方 CLI）
set -euo pipefail
MODE=system
for a in "$@"; do
  case "$a" in
    --user) MODE=user ;;
    --no-systemd) MODE=none ;;
    --update) MODE=update ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "不认识的参数：$a（--user / --no-systemd / --update）" >&2; exit 1 ;;
  esac
done
SRC=$(cd "$(dirname "$0")" && pwd)
say() { echo "==> $*"; }
die() { echo "错误：$*" >&2; exit 1; }

if [ "$MODE" = update ]; then
  # 面板里点「立即更新」：从安装记录里找安装目录和原来的安装方式
  [ -n "${AGY_ROOT:-}" ] || die "--update 需要 AGY_ROOT（面板会自动传）"
  ROOT=$AGY_ROOT
  [ -d "$ROOT" ] || die "安装目录 $ROOT 不存在"
  INSTALL_MODE=$(sed -n 's/.*"mode": *"\([a-z]*\)".*/\1/p' "$ROOT/install-info.json" 2>/dev/null | head -1)
  INSTALL_MODE=${INSTALL_MODE:-system}
elif [ "$MODE" = user ]; then
  ROOT=${AGY_ROOT:-$HOME/acp-ant}
  INSTALL_MODE=user
else
  ROOT=${AGY_ROOT:-/opt/acp-ant}
  INSTALL_MODE=$MODE
fi
PORT=${AGY_PORT:-8095}
HOST=${AGY_HOST:-127.0.0.1}
RUN_USER=${SUDO_USER:-$(id -un)}
if [ "$MODE" = user ] || [ "$MODE" = update ]; then RUN_USER=$(id -un); fi   # 用户服务 / 面板更新：就是当前用户
SUDO=""
if [ "$(id -u)" != 0 ] && [ "$MODE" != user ] && [ "$MODE" != update ]; then SUDO="sudo"; fi

command -v python3 >/dev/null || die "需要 python3（Ubuntu / Debian：sudo apt install -y python3）"
command -v curl >/dev/null || die "需要 curl（Ubuntu / Debian：sudo apt install -y curl）"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "需要 Python 3.10 或更新（现在是 $PYV）"

# ---- Python 虚拟环境：不能只看 venv/bin/python 在不在——缺 python3-venv 时会留下一个没有 pip 的半成品
venv_ok() { [ -x "$1/bin/python" ] && "$1/bin/python" -m pip --version >/dev/null 2>&1; }
make_venv() {   # 新建到 $1；成功返回 0，失败把半成品删掉返回 1
  rm -rf "$1"
  python3 -m venv "$1" >/dev/null 2>&1 && venv_ok "$1" && return 0
  rm -rf "$1"
  return 1
}
venv_hint() {
  echo "Ubuntu / Debian：sudo apt install -y python$PYV-venv（没有这个包名就装 python3-venv）"
  echo "CentOS / Rocky / Alma：sudo dnf install -y python3-pip；Alpine：apk add py3-pip"
}

if [ "$MODE" != update ]; then
  say "安装目录 $ROOT（运行用户 $RUN_USER，方式：$INSTALL_MODE）"
  if [ ! -d "$ROOT" ]; then
    if mkdir -p "$ROOT" 2>/dev/null; then :
    elif [ -n "$SUDO" ]; then $SUDO mkdir -p "$ROOT" && $SUDO chown "$RUN_USER" "$ROOT"
    else die "建不了 $ROOT（没有权限）；换一个目录：AGY_ROOT=~/acp-ant ./install.sh --user"
    fi
  fi
  [ -w "$ROOT" ] || die "$ROOT 不可写（属于 $(stat -c %U "$ROOT")）；用那个用户运行，或 sudo chown $RUN_USER $ROOT"
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
fi

say "Python 虚拟环境和依赖"
if venv_ok "$ROOT/venv"; then
  :
else
  [ -d "$ROOT/venv" ] && say "虚拟环境不完整（没有 pip），删掉重建"
  if ! make_venv "$ROOT/venv"; then
    # 不是 --user 安装、有 apt 并且能用 root / sudo 时自动补装 venv 组件；其它情况给出命令
    if [ "$MODE" != user ] && [ "$MODE" != update ] && command -v apt-get >/dev/null && { [ "$(id -u)" = 0 ] || sudo -n true 2>/dev/null || [ -t 0 ]; }; then
      say "缺少 Python 的 venv / pip 组件，自动安装 python$PYV-venv"
      $SUDO apt-get install -y "python$PYV-venv" >/dev/null 2>&1 || $SUDO apt-get install -y python3-venv >/dev/null 2>&1 \
        || { $SUDO apt-get update >/dev/null 2>&1 && { $SUDO apt-get install -y "python$PYV-venv" >/dev/null 2>&1 || $SUDO apt-get install -y python3-venv >/dev/null 2>&1; }; } || true
      make_venv "$ROOT/venv" || { venv_hint >&2; die "建不了 Python 虚拟环境（缺 venv / pip 组件），装好后重新运行 ./install.sh"; }
    else
      venv_hint >&2
      die "建不了 Python 虚拟环境（缺 venv / pip 组件），装好后重新运行 ./install.sh"
    fi
  fi
fi
"$ROOT/venv/bin/python" -m pip install -q --disable-pip-version-check --upgrade pip || die "pip 升级失败（网络？）"
"$ROOT/venv/bin/python" -m pip install -q --disable-pip-version-check -r "$SRC/requirements.txt" || die "装依赖失败（网络？能不能访问 pypi.org）"

say "复制程序文件"
install -m 644 "$SRC/acp_ant.py" "$SRC/acp_panel.py" "$SRC/panel.html" "$ROOT/"
sed -e "s#^ROOT=\${AGY_ROOT:-/opt/acp-ant}#ROOT=\${AGY_ROOT:-$ROOT}#" \
    -e "s#^AGY=\${AGY_BIN:-\$ROOT/bin/agy}#AGY=\${AGY_BIN:-${AGY_BIN:-$ROOT/bin/agy}}#" \
    "$SRC/scripts/account.sh" > "$ROOT/account.sh.tmp" && mv "$ROOT/account.sh.tmp" "$ROOT/account.sh"
chmod 755 "$ROOT/account.sh"
install -m 755 "$SRC/scripts/update.sh" "$ROOT/update.sh"
install -m 644 "$SRC/scripts/smoke_test.py" "$SRC/scripts/agent_test.py" "$SRC/scripts/acp_probe.py" "$ROOT/"
# 安装记录：面板据此判断能不能一键更新（源码目录是 git 仓库、服务能自动重启）
SRC_GIT=""; git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1 && SRC_GIT=$SRC
VER=$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$SRC/acp_ant.py")
printf '{"mode": "%s", "src": "%s", "version": "%s", "installed_at": "%s"}\n' \
  "$INSTALL_MODE" "$SRC_GIT" "$VER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ROOT/install-info.json"

if [ "$MODE" = update ]; then
  say "文件已更新到 $VER（网关重启后生效）"
  exit 0
fi

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

render_unit() {   # $1 = system | user
  if [ "$1" = user ]; then
    sed -e '/^User=/d' -e 's#^WantedBy=multi-user.target#WantedBy=default.target#' "$SRC/deploy/acp-ant.service"
  else
    sed -e "s#@USER@#$RUN_USER#g" "$SRC/deploy/acp-ant.service"
  fi | sed -e "s#@ROOT@#$ROOT#g" -e "s#@PORT@#$PORT#g" -e "s#@HOST@#$HOST#g"
}

if [ "$MODE" = system ]; then
  command -v systemctl >/dev/null || die "没有 systemd；用 --no-systemd 安装后自己启动"
  say "安装系统服务 acp-ant（$HOST:$PORT）"
  render_unit system | $SUDO tee /etc/systemd/system/acp-ant.service >/dev/null
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now acp-ant
  sleep 2
  $SUDO systemctl restart acp-ant   # 已经在运行（升级）时也要重启才会用上新代码
  sleep 3
  systemctl is-active acp-ant >/dev/null && say "服务已启动" || echo "服务没起来，看日志：journalctl -u acp-ant -n 50"
  LOGS="journalctl -u acp-ant -f"
elif [ "$MODE" = user ]; then
  command -v systemctl >/dev/null || die "没有 systemd；用 --no-systemd 安装后自己启动"
  [ -n "${XDG_RUNTIME_DIR:-}" ] || export XDG_RUNTIME_DIR=/run/user/$(id -u)
  systemctl --user show-environment >/dev/null 2>&1 \
    || die "连不上当前用户的 systemd（systemctl --user）。请用 SSH 直接登录这个用户再运行（不要用 su / sudo -u 切换过来）"
  say "安装用户服务 acp-ant（$HOST:$PORT，systemctl --user）"
  mkdir -p "$HOME/.config/systemd/user"
  render_unit user > "$HOME/.config/systemd/user/acp-ant.service"
  systemctl --user daemon-reload
  systemctl --user enable --now acp-ant
  sleep 2
  systemctl --user restart acp-ant
  sleep 3
  systemctl --user is-active acp-ant >/dev/null && say "服务已启动" || echo "服务没起来，看日志：journalctl --user -u acp-ant -n 50"
  # 让服务在退出 SSH 后、服务器重启后也继续运行
  if [ "$(loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null)" != yes ]; then
    if loginctl enable-linger "$(id -un)" 2>/dev/null; then
      say "已开启「退出登录后继续运行」（loginctl enable-linger）"
    else
      echo "注意：没能开启「退出登录后继续运行」。退出 SSH 后服务会停；请让管理员运行一次：sudo loginctl enable-linger $(id -un)"
    fi
  fi
  LOGS="journalctl --user -u acp-ant -f"
else
  say "没装服务。手动启动："
  echo "  set -a; . $ROOT/gateway.env; set +a; $ROOT/venv/bin/uvicorn acp_ant:app --app-dir $ROOT --host $HOST --port $PORT"
  LOGS="（自己启动时看终端输出）"
fi

cat <<EOF

安装完成（ACP-Ant $VER）。
网页控制面板：http://$HOST:$PORT/   （装在服务器上时，用反向代理绑定域名后用 https://你的域名/ 打开）
  第一次登录的初始密码保存在 $ROOT/panel-initial-password.txt（查看：cat $ROOT/panel-initial-password.txt），
  在面板「设置」里改成自己的密码后，这个文件会自动删除。
在面板里就能添加账号、登录 Google、换代理、看额度、开关账号、检查和安装新版本；也可以用命令行：
  $ROOT/account.sh add g1
查看账号：  $ROOT/account.sh list
网关密钥：  grep AGY_GATEWAY_KEY $ROOT/gateway.env
接口地址：  http://$HOST:$PORT/v1   （OpenAI 兼容，Bearer 用上面的密钥）
看日志：    $LOGS
EOF
