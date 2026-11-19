#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
if [ "$#" -eq 0 ]; then
    exec python3 ./launch-gui.py
fi
exec python3 ./bench "$@"
