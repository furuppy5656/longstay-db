#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ロングステイ宿データベース ローカルサーバ（API付き）

`python3 -m http.server` の置き換え。標準ライブラリのみで実装。
- 静的配信: index.html / data.json などをそのまま配る（GET）
- POST /api/check-links : check_links.py を同期実行し、レポートを返す（数秒）
- POST /api/ai-update   : ローカル claude CLI でデータ最新化をバックグラウンド実行（数分）
- GET  /api/ai-update/status : 上記ジョブの進捗・ログ・結果を返す（ページがポーリング）

起動: python3 server.py [PORT]   （省略時 5055）
"""

import json
import os
import sys
import subprocess
import threading
import datetime
import http.server
import socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5055
PYBIN = sys.executable or "python3"

STATUS_PATH = os.path.join(HERE, "link_status.json")
REPORT_PATH = os.path.join(HERE, "link_report.md")
AI_LOG_PATH = os.path.join(HERE, "ai_update.log")

# --- AI更新ジョブの状態（同時実行は1つだけ）---
_job_lock = threading.Lock()
_job = {
    "state": "idle",      # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "summary": "",
    "error": "",
}


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def run_check_links():
    """check_links.py を同期実行し、結果サマリ＋レポートを返す。"""
    proc = subprocess.run(
        [PYBIN, os.path.join(HERE, "check_links.py")],
        cwd=HERE, capture_output=True, text=True, timeout=600,
    )
    summary = {}
    try:
        summary = json.loads(_read(STATUS_PATH))
    except json.JSONDecodeError:
        pass
    return {
        "ok": proc.returncode == 0,
        "checked_at": summary.get("checked_at"),
        "total_facilities": summary.get("total_facilities"),
        "total_links": summary.get("total_links"),
        "suspicious_count": summary.get("suspicious_count"),
        "whitelisted_count": summary.get("whitelisted_count"),
        "report_md": _read(REPORT_PATH),
        "stderr": proc.stderr[-2000:] if proc.returncode != 0 else "",
    }


def _ai_update_worker():
    """ai_update.py をサブプロセス実行し、ジョブ状態を更新する。"""
    try:
        with open(AI_LOG_PATH, "w", encoding="utf-8") as logf:
            logf.write(f"[{_now()}] AI更新を開始します…\n")
            logf.flush()
            proc = subprocess.run(
                [PYBIN, os.path.join(HERE, "ai_update.py")],
                cwd=HERE, stdout=logf, stderr=subprocess.STDOUT,
                text=True, timeout=1800,
            )
        # ai_update.py は最後に結果サマリを ai_update_result.md に書く
        summary = _read(os.path.join(HERE, "ai_update_result.md")).strip()
        with _job_lock:
            if proc.returncode == 0:
                _job["state"] = "done"
                _job["summary"] = summary or "（サマリなし）更新が完了しました。"
            else:
                _job["state"] = "error"
                _job["error"] = (summary or _read(AI_LOG_PATH)[-1500:]
                                 or f"exit code {proc.returncode}")
            _job["finished_at"] = _now()
    except subprocess.TimeoutExpired:
        with _job_lock:
            _job["state"] = "error"
            _job["error"] = "タイムアウト（30分）。処理が長すぎたため中断しました。"
            _job["finished_at"] = _now()
    except Exception as e:  # noqa: BLE001
        with _job_lock:
            _job["state"] = "error"
            _job["error"] = f"{type(e).__name__}: {e}"
            _job["finished_at"] = _now()


def start_ai_update():
    with _job_lock:
        if _job["state"] == "running":
            return False
        _job.update(state="running", started_at=_now(),
                    finished_at=None, summary="", error="")
    threading.Thread(target=_ai_update_worker, daemon=True).start()
    return True


def ai_update_status():
    with _job_lock:
        snap = dict(_job)
    snap["log_tail"] = _read(AI_LOG_PATH)[-4000:]
    return snap


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def log_message(self, fmt, *args):  # 静かめに
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/api/ai-update/status":
            return self._send_json(ai_update_status())
        return super().do_GET()

    def do_POST(self):
        path = self.path.rstrip("/")
        try:
            if path == "/api/check-links":
                return self._send_json(run_check_links())
            if path == "/api/ai-update":
                started = start_ai_update()
                return self._send_json(
                    {"started": started,
                     "message": "AI更新を開始しました。" if started
                                else "すでに実行中です。"},
                    code=200 if started else 409)
        except subprocess.TimeoutExpired:
            return self._send_json({"ok": False, "error": "処理がタイムアウトしました。"}, 504)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)
        return self._send_json({"error": "not found"}, 404)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    os.chdir(HERE)
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print(f"ロングステイ宿DB サーバ起動: http://0.0.0.0:{PORT}/  (Ctrl-C で停止)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n停止しました。")


if __name__ == "__main__":
    main()
