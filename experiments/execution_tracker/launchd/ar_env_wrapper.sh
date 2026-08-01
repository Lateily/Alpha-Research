#!/bin/bash
# launchd 入口:从 600 私有文件读取凭证后执行目标命令(密钥不再进 plist)
[ -f "$HOME/.ar_env" ] && source "$HOME/.ar_env"
exec "$@"
