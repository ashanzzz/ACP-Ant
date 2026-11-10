#!/bin/bash
# ACP-Ant 账号管理：每个 Google 账号一个独立目录，可以给每个账号配一个独立代理节点。
#   account.sh add <名字>      新加账号：输入代理（不回显）→ 测代理出口 IP → 用官方 agy 登录 Google（可重复运行，断点续做）
#   account.sh login <名字>    重新登录（代理不变）
#   account.sh token <名字>    用这个 Google 账号的 refresh_token 登录（不回显输入；账号还没有就先建、先设代理）
#   account.sh proxy <名字>    换代理节点（不回显输入）
#   account.sh check <名字>    真发一句话看能不能用；被 Google 要求验证时打印验证网址
#   account.sh list            列出账号、代理（只显示主机和端口）、出口 IP、登录状态
#   account.sh remove <名字>   删除账号目录（会先确认）
# 账号目录 $AGY_ROOT/accounts/<名字>：HOME 指向这里，登录凭据只存在这里（不用系统钥匙串，账号之间互不串）。
# 代理写在 <名字>/proxy.env（权限 600），只给这个账号的 agy 用；支持 http://、https://、socks5://（可带 用户:密码@）。
# 代理是可选的（1.4.0 起默认不强制）；想强制每个账号都有代理：AGY_REQUIRE_PROXY=1（网关也要设同样的环境变量）。
set -euo pipefail
shopt -s nullglob
ROOT=${AGY_ROOT:-/opt/acp-ant}
AGY=${AGY_BIN:-$ROOT/bin/agy}
ACC=${AGY_ACCOUNTS:-$ROOT/accounts}
REQUIRE_PROXY=${AGY_REQUIRE_PROXY:-0}
ME=$(basename "$0")

die() { echo "错误：$*" >&2; exit 1; }
need_name() { [[ "${1:-}" =~ ^[a-zA-Z0-9_@+][a-zA-Z0-9_.@+-]{0,63}$ && "${1:-}" != *..* ]] || die "名字只能用字母、数字和 - _ . @ +（最长 64 个字符），可以直接用 Google 邮箱，例如 g1、me@gmail.com"; }
mask() { sed -E 's#^([a-z0-9]+://)(.*@)?([^@/]+).*#\1\3#' <<<"$1"; }   # 只留 协议://主机:端口，去掉账号密码
no_proxy_ok() { [ "$REQUIRE_PROXY" = 0 ] || [ "$REQUIRE_PROXY" = false ] || [ "$REQUIRE_PROXY" = no ]; }

proxy_of() { [ -f "$ACC/$1/proxy.env" ] || { echo "（不用代理）"; return; }; ( set -a; . "$ACC/$1/proxy.env"; printf '%s' "$HTTPS_PROXY" ); }

load_proxy() {
  local d=$ACC/$1
  HTTPS_PROXY=""; HTTP_PROXY=""
  if [ -f "$d/proxy.env" ]; then
    # shellcheck disable=SC1090
    set -a; . "$d/proxy.env"; set +a
  elif ! no_proxy_ok; then
    die "账号 $1 还没有设置代理（先运行：$ME proxy $1；不用代理请设 AGY_REQUIRE_PROXY=0）"
  fi
}

run_agy() {   # 用账号的 HOME 和代理运行 agy；不继承桌面会话的钥匙串（DBUS），凭据只落在账号目录
  local name=$1; shift
  local d=$ACC/$name
  ( load_proxy "$name"
    exec env -i HOME="$d" PATH="/usr/bin:/bin" TERM="${TERM:-xterm}" LANG=C.UTF-8 \
      ${HTTPS_PROXY:+HTTPS_PROXY="$HTTPS_PROXY" https_proxy="$HTTPS_PROXY"} \
      ${HTTP_PROXY:+HTTP_PROXY="$HTTP_PROXY" http_proxy="$HTTP_PROXY"} \
      NO_PROXY="127.0.0.1,localhost" no_proxy="127.0.0.1,localhost" \
      "$AGY" "$@" )
}

set_proxy() {
  local name=$1 d=$ACC/$1 p ip cc
  echo "请输入账号 $name 的代理节点地址（输入时不显示），格式例如："
  echo "  http://用户名:密码@1.2.3.4:8080   或   socks5://用户名:密码@1.2.3.4:1080"
  echo "（粘贴后屏幕上看不到字是正常的，直接按回车）"
  read -rs -p "代理地址（可选，直接回车 = 不用代理）：" p; echo
  if [ -z "$p" ]; then
    if no_proxy_ok; then echo "不用代理，这个账号走服务器本机网络。"; return 0; fi
    die "这台网关要求每个账号都有代理（AGY_REQUIRE_PROXY=1）"
  fi
  [[ "$p" =~ ^(https?|socks5h?)://[^[:space:]]+:[0-9]{2,5}/?$ ]] || die "格式不对，需要 协议://[用户:密码@]主机:端口"
  echo "正在通过这个代理测出口 IP…"
  ip=$(curl -s --max-time 20 -x "$p" https://api.ipify.org || true)
  [ -n "$ip" ] || die "代理连不上（$(mask "$p")），没有保存"
  cc=$(curl -s --max-time 20 -x "$p" "https://ipinfo.io/$ip/country" 2>/dev/null | tr -d '[:space:]' || true)
  for f in "$ACC"/*/egress_ip.txt; do
    [ -f "$f" ] && [ "$f" != "$d/egress_ip.txt" ] && [ "$(cat "$f")" = "$ip" ] && echo "提醒：出口 IP $ip 和账号 $(basename "$(dirname "$f")") 的一样，两个账号会共用同一个 IP"
  done
  umask 077
  printf 'HTTPS_PROXY=%q\nHTTP_PROXY=%q\n' "$p" "$p" > "$d/proxy.env"
  chmod 600 "$d/proxy.env"
  echo "$ip" > "$d/egress_ip.txt"
  echo "已保存：$(mask "$p")，出口 IP $ip（${cc:-国家未知}）"
}

do_login() {
  local name=$1 d=$ACC/$1
  mkdir -p "$d/workspace" "$d/.gemini"
  echo
  echo "== 登录账号 $name（代理 $(mask "$(proxy_of "$name")")）=="
  echo "下面会出现一个 Google 授权网址：复制到您自己电脑的浏览器里打开，选这个账号并同意授权。"
  echo "授权后浏览器会跳到一个打不开的 localhost 网址，或者页面上显示一串授权码——"
  echo "把整串网址（或授权码）复制回来，在这里粘贴，然后按回车。"
  echo
  run_agy "$name" acp --login --gemini-dir "$d/.gemini" --disable-telemetry
  echo
  status "$name"
}

do_token() {   # refresh_token 写进 agy 自己的登录文件（和浏览器登录后的格式一样），agy 用它换新令牌；不能用就恢复原来的
  local name=$1 d=$ACC/$1 rt f old="" email
  echo "请粘贴账号 $name 的 Google refresh_token（以 1// 开头；输入时不显示，粘贴后直接按回车）。"
  echo "只能用 Antigravity 登录得到的 refresh_token，Gemini CLI 等其它程序的不能用。"
  read -rs -p "refresh_token：" rt; echo
  rt=$(tr -d '[:space:]"' <<<"$rt")
  [[ "$rt" =~ ^1//[0-9A-Za-z_-]{20,500}$ ]] || die "这看起来不是 Google 的 refresh_token（一般以 1// 开头，只含字母、数字、- 和 _）"
  f=$d/.gemini/antigravity-cli/antigravity-oauth-token
  mkdir -p "$d/workspace" "$(dirname "$f")" && chmod 700 "$d/.gemini" "$(dirname "$f")"
  if [ -f "$f" ]; then old=$f.before-token; cp -p "$f" "$old"; fi
  ( umask 077
    printf '{"token":{"access_token":"","token_type":"Bearer","refresh_token":"%s","expiry":"2000-01-01T00:00:00Z"},"auth_method":"consumer"}' "$rt" > "$f.tmp"
    mv "$f.tmp" "$f" )
  rt=""
  echo "正在检测…"
  if logged_in "$name"; then
    [ -z "$old" ] || rm -f "$old"
    email=$(grep -o '"id_token_email" *: *"[^"]*"' "$f" | sed -E 's/.*: *"([^"]*)"$/\1/' || true)
    echo "登录成功${email:+（$email）}"
    for g in "$ACC"/*/.gemini/antigravity-cli/antigravity-oauth-token; do
      o=${g#"$ACC"/}; o=${o%%/*}
      [ -n "$email" ] && [ "$o" != "$name" ] && grep -q "\"$email\"" "$g" && echo "提醒：账号 $o 登录的也是这个 Google 账号" || true
    done
    status "$name"
    echo "网关正在运行的话，在面板里点这个账号的「清除冷却」（或调用 /admin/reset/$name），让它换用新的登录。"
  else
    if [ -n "$old" ]; then mv "$old" "$f"; else rm -f "$f"; fi
    die "这个 refresh_token 用不了（可能已经失效、被撤销，不是 Antigravity 登录得到的，或者代理连不上）；原来的登录没有改动"
  fi
}

models_out() { (cd "$ACC/$1/workspace" 2>/dev/null && run_agy "$1" models 2>&1) || true; }
# 只有真的列出了模型才算已登录（用管道 + grep -q 在 pipefail 下会误判）
logged_in() { local out; out=$(models_out "$1"); grep -q -i "gemini" <<<"$out" && ! grep -q -i "sign in" <<<"$out"; }

status() {
  local name=$1 out
  out=$(models_out "$name")
  if grep -q -i "gemini" <<<"$out" && ! grep -q -i "sign in" <<<"$out"; then
    echo "  $name：已登录，可用模型："; grep -v -i "^fetching" <<<"$out" | sed 's/^/    /'
  elif grep -q -i "sign in" <<<"$out"; then
    echo "  $name：未登录"
  else
    echo "  $name：状态不明（可能是代理连不上）：$(head -c 200 <<<"$out" | tr '\n' ' ')"
  fi
}

cmd=${1:-}; name=${2:-}
case "$cmd" in add|check|login|token|list) [ -x "$AGY" ] || die "找不到 agy：$AGY（先安装官方 Antigravity CLI，或设置 AGY_BIN）" ;; esac
case "$cmd" in
  add)
    # 可以重复运行：没设代理就设代理，没登录就登录，都好了就显示状态（中途关掉窗口也能接着做）
    need_name "$name"; d=$ACC/$name
    mkdir -p "$d/workspace" && chmod 700 "$d"
    if [ -f "$d/proxy.env" ]; then
      echo "账号 $name 已经设置过代理 $(mask "$(proxy_of "$name")")（要换代理：$ME proxy $name）"
    else
      echo "【第 1 步 / 共 2 步】设置账号 $name 的代理节点（可选）"
      set_proxy "$name"
    fi
    if logged_in "$name"; then
      echo "账号 $name 已经登录好了，不用再登录。"; status "$name"
    else
      echo; echo "【第 2 步 / 共 2 步】登录 Google 账号"
      do_login "$name"
    fi ;;
  check)
    # 真发一句话试试这个账号能不能用；Google 要求验证账号时，打印验证网址（用这个账号在浏览器里打开完成验证）
    need_name "$name"; [ -d "$ACC/$name" ] || die "没有账号 $name"
    echo "正在用账号 $name 试一句话（走它自己的代理）…"
    out=$(cd "$ACC/$name/workspace" && run_agy "$name" -p "Reply with exactly one word: OK" --output-format json 2>&1 || true)
    if grep -q '"status":"SUCCESS"\|"status": "SUCCESS"' <<<"$out"; then
      echo "账号 $name 正常，可以用。"
      echo "（如果网关之前因为验证把它暂停了，几分钟内会自动恢复）"
    elif grep -q -i "verify your account" <<<"$out"; then
      url=$(grep -o -E 'https://accounts\.google\.com/v3/signin/continue[^" \\]*' <<<"$out" | head -1 | sed 's/\\u0026/\&/g')
      echo
      echo "账号 $name 被 Google 要求验证，暂时不能用。请这样做："
      echo "  1. 复制下面这个网址，在您电脑的浏览器里打开（浏览器要登录的是 $name 用的那个 Google 账号）"
      echo "  2. 按页面提示完成验证（一般是手机号 / 短信验证码）"
      echo "  3. 验证完再运行一次：$ME check $name"
      echo
      echo "$url"
      echo
    else
      echo "账号 $name 出错了：$(head -c 400 <<<"$out")"
    fi ;;
  login) need_name "$name"; [ -d "$ACC/$name" ] || die "没有账号 $name"; do_login "$name" ;;
  token)
    need_name "$name"; d=$ACC/$name
    mkdir -p "$d/workspace" && chmod 700 "$d"
    if [ ! -f "$d/proxy.env" ]; then
      echo "【第 1 步 / 共 2 步】设置账号 $name 的代理节点（可选，直接回车 = 不用代理）"; set_proxy "$name"; echo; echo "【第 2 步 / 共 2 步】用 refresh_token 登录"
    fi
    do_token "$name" ;;
  proxy) need_name "$name"; [ -d "$ACC/$name" ] || die "没有账号 $name"; set_proxy "$name" ;;
  list)
    for d in "$ACC"/*/; do
      n=$(basename "$d")
      echo "账号 $n  代理 $(mask "$(proxy_of "$n")")  出口 IP $(cat "$d/egress_ip.txt" 2>/dev/null || echo '?')$([ -f "$d/disabled" ] && echo '  （已在面板关闭，不会被调用）')"
      status "$n"
    done ;;
  remove)
    need_name "$name"; [ -d "$ACC/$name" ] || die "没有账号 $name"
    read -r -p "确认删除账号 $name 的目录（含登录凭据）？输入 yes：" ok; [ "$ok" = yes ] && rm -rf "${ACC:?}/$name" && echo "已删除" ;;
  *) sed -n '2,12p' "$0" ;;
esac
