#!/bin/bash
# ロングステイ宿データベース ローカルサーバ起動スクリプト
# ダブルクリック or `bash start-longstay-db.command` で起動。
# python3 -m http.server を nohup でバックグラウンド起動し、ログを server.log に出力する。

set -e

PORT=5055
DIR="$HOME/services/longstay-db"
TSIP="100.67.251.19"   # Tailscale Macノード
LOG="$DIR/server.log"

cd "$DIR"

# 既に同ポートで動いていれば二重起動しない
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "✅ すでに起動中です（ポート $PORT）。"
else
  nohup python3 -m http.server "$PORT" >> "$LOG" 2>&1 &
  sleep 1
  echo "🚀 起動しました（ポート $PORT、PID $!）。ログ: $LOG"
fi

echo ""
echo "  ローカル:        http://localhost:$PORT/"
echo "  Tailscale経由:   http://$TSIP:$PORT/"
echo ""
echo "  iPhone(Brave)からは上の Tailscale経由 URL（httpsではなくhttp）でアクセス。"
echo "  停止: pkill -f 'http.server $PORT'"
echo ""
