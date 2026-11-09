#!/bin/bash
# 面板「立即更新」调用：在源码目录（git clone 下来的 ACP-Ant）拉取最新版本，再用 install.sh --update 复制文件、装依赖。
# 不动 gateway.env、账号、面板密码和统计；网关随后自己重启（systemd 会把它拉起来）。
# 也可以手动运行：AGY_ROOT=/opt/acp-ant /opt/acp-ant/update.sh /opt/acp-ant-src
set -euo pipefail
SRC=${1:?用法：update.sh <源码目录>}
[ -n "${AGY_ROOT:-}" ] || { echo "需要 AGY_ROOT" >&2; exit 1; }
cd "$SRC"
git rev-parse --git-dir >/dev/null 2>&1 || { echo "$SRC 不是 git 仓库，没法自动更新" >&2; exit 1; }
[ -w .git ] || { echo "没有权限写 $SRC（属于 $(stat -c %U .git)），请在服务器上手动运行：cd $SRC && git pull && ./install.sh" >&2; exit 1; }
BRANCH=$(git rev-parse --abbrev-ref HEAD)
OLD=$(git rev-parse --short HEAD)
echo "==> 拉取最新代码（$BRANCH，当前 $OLD）"
GIT_TERMINAL_PROMPT=0 git fetch --quiet origin "$BRANCH"
GIT_TERMINAL_PROMPT=0 git reset --hard --quiet "origin/$BRANCH"
echo "==> 已更新到 $(git rev-parse --short HEAD)"
git log --oneline "$OLD..HEAD" | head -20
./install.sh --update
