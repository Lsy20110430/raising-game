#!/bin/sh
# 养成小游戏启动器：默认进终端界面，sh run.sh web 起网页版。
# Termux 默认不设 LANG（C locale），Python 会把 stdout 当 ascii，一 print 中文就 UnicodeEncodeError，
# 所以统一打开 UTF-8 模式再启动。

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$DIR" || exit 1

PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "找不到 python3。Termux 里先执行：pkg install python" >&2
    exit 1
fi

if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
    trap 'termux-wake-unlock' EXIT INT TERM HUP
fi

case "${1:-tui}" in
    tui|cli|term)
        "$PY" tui.py
        ;;
    web|serve|server)
        HOST=${HOST:-127.0.0.1}
        PORT=${2:-${PORT:-8765}}
        export HOST PORT
        echo "网页版：默认 http://127.0.0.1:$PORT/（端口被占会自动顺延，看下面的实际地址；Ctrl+C 结束）"
        "$PY" server.py
        ;;
    *)
        echo "用法：sh run.sh [tui|web]" >&2
        exit 2
        ;;
esac
