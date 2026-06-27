#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI更新ワーカー: ローカル claude CLI（サブスク=無課金）で data.json を最新化する。

server.py の「🤖 AIで最新化」ボタンから呼ばれる。手動でも実行可:
    python3 ai_update.py

データソースは **Notion が「正」**、data.json はキャッシュ。この処理は両者を一致させる。

流れ:
  0. Notion → data.json を pull（最新化）。Notion 未設定/到達不可なら既存 data.json で続行。
  1. data.json をバックアップ。
  2. check_links.py を実行（このスクリプトが回す → claude に Bash 権限を渡さない）。
  3. claude を -p（非対話）で起動。claude は link_report.md を読み、要確認施設を
     Web で確認して data.json を直し、変更内容を ai_update_result.md に書く。
     付与ツールは Read/Edit/Write/WebSearch/WebFetch/Grep/Glob のみ（Bashなし＝安全）。
  4. data.json が壊れていないか検証。壊れていればバックアップから復元。
  5. data.json → Notion を push（書き戻し）＋ pull（_notion_id/order を正規化）。
     Notion 未設定/到達不可なら書き戻しはスキップ（ローカル更新は維持）。
  6. 変更があれば git にコミット（revert で戻せる安全網）。

前提: 一度ターミナルで `claude` → `/login`（Pro/Max。API keyではない）済みであること。
"""

import os
import sys
import glob
import json
import shutil
import subprocess
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
RESULT = os.path.join(HERE, "ai_update_result.md")
PYBIN = sys.executable or "python3"

# claude を相乗りさせないため除去する環境変数（無課金パターンの定石）
_STRIP_ENV = [
    "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_OAUTH_SCOPES",
    "CLAUDE_CODE_SESSION_ID",
]


def log(msg):
    print(f"[{datetime.datetime.now().astimezone().strftime('%H:%M:%S')}] {msg}",
          flush=True)


def resolve_claude():
    p = shutil.which("claude")
    if p:
        return p
    cands = sorted(glob.glob(os.path.expanduser(
        "~/.nvm/versions/node/*/bin/claude")))
    return cands[-1] if cands else None


def clean_env():
    env = dict(os.environ)
    for k in _STRIP_ENV:
        env.pop(k, None)
    return env


def write_result(text):
    with open(RESULT, "w", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")


def git(*args):
    return subprocess.run(["git", *args], cwd=HERE,
                          capture_output=True, text=True)


def notion_pull_safe():
    """Notion → data.json（best-effort）。設定が無ければ何もしない。戻り値: 件数 or None。"""
    try:
        import notion_sync
        if not notion_sync.is_configured():
            log("Notion 未設定。既存 data.json で続行します。")
            return None
        n = notion_sync.pull()
        log(f"Notion から {n} 件を pull しました。")
        return n
    except Exception as e:  # noqa: BLE001
        log(f"Notion pull に失敗（既存 data.json で続行）: {e}")
        return None


def notion_push_safe():
    """data.json → Notion 書き戻し＋pullで正規化（best-effort）。戻り値: サマリ文字列 or None。"""
    try:
        import notion_sync
        if not notion_sync.is_configured():
            log("Notion 未設定。書き戻しはスキップします。")
            return None
        s = notion_sync.push()
        n = notion_sync.pull()
        msg = (f"Notion へ書き戻し: 新規 {s['created']} / 更新 {s['updated']} "
               f"/ アーカイブ {s['archived']}（→ {n} 件に正規化）")
        log(msg)
        return msg
    except Exception as e:  # noqa: BLE001
        log(f"Notion 書き戻しに失敗（ローカル更新は維持）: {e}")
        return f"⚠️ Notion 書き戻し失敗: {e}"


PROMPT_TMPL = """\
あなたはローカルのClaude Codeです。作業ディレクトリはこのフォルダ（ロングステイ宿データベース）。
今日は {today} です。

このフォルダの data.json に宿の配列があり、index.html がそれを読んで表示します。
スキーマと運用ルールは CLAUDE.md に書いてあります（必要なら読む）。
直前に check_links.py を実行済みで、link_report.md が最新です。

【タスク】リンク切れ・休業の最新化（data.json のメンテ）
1. link_report.md を読む。「要確認」に挙がった施設を対象にする。
2. 各対象施設について WebSearch / WebFetch で現状を確認し、確証が取れたものだけ data.json を直す:
   - 公式サイトのURLが変わっていたら、該当 links のURLを新しい公式に差し替える。
   - 第三者まとめ記事しか無い施設で公式サイトが見つかれば、公式に差し替える（label例「公式サイト」）。
   - 休業・閉鎖が確実なら body 冒頭に「※{today}時点 休業の可能性あり」等の注記を入れる。
     完全閉鎖が確実な場合のみ、その施設の要素ごと配列から削除してよい。
3. 厳守事項:
   - data.json は JSON として壊さない。既存フィールド構成（name/pref/region/loc/tags/body/links/feat）を維持。
   - 各要素に "_notion_id" があれば**絶対に消さない・書き換えない**（Notion同期の鍵）。施設を丸ごと削除する場合のみ、その要素ごと消えてよい。
   - links は ["表示名","URL"] の配列。Googleマップのリンクは index.html が自動生成するので data.json に入れない。
   - 推測でURLを書き換えない。検索/閲覧で確認できた変更だけ行う。確証が無ければ触らない。
   - data.json と ai_update_result.md 以外のファイルは変更しない。git操作はしない。
4. 最後に、行った変更を日本語の箇条書きで ai_update_result.md に上書き保存する。
   形式例: 「- <施設名>: <旧URL> → <新URL>（理由: ○○で確認）」。
   変更が無ければ「変更なし（要確認リンクはbotブロック等で実際は健全、または確証が取れず）」と書く。
"""


def main():
    if not os.path.exists(DATA):
        write_result("エラー: data.json が見つかりません。")
        return 1

    claude = resolve_claude()
    if not claude:
        write_result("エラー: claude CLI が見つかりません。`npm i -g @anthropic-ai/claude-code` 等で導入し、"
                     "一度 `claude` → `/login` してください。")
        return 1

    today = datetime.date.today().isoformat()

    # 0) Notion を「正」として data.json を最新化（バックアップより前に行い、復元先を整える）
    notion_pull_safe()

    ts = datetime.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(HERE, f"data.json.bak.{ts}")
    shutil.copy2(DATA, backup)
    log(f"data.json をバックアップ: {os.path.basename(backup)}")

    # 1) リンク点検（claude に Bash を渡さず、こちらで実行）
    log("check_links.py を実行中…")
    r = subprocess.run([PYBIN, os.path.join(HERE, "check_links.py")],
                       cwd=HERE, capture_output=True, text=True, timeout=600)
    log(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "（点検完了）")

    # 2) claude で最新化
    prompt = PROMPT_TMPL.format(today=today)
    argv = [
        claude, "-p", prompt,
        "--add-dir", HERE,
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read", "Edit", "Write",
        "WebSearch", "WebFetch", "Grep", "Glob",
    ]
    log("claude を起動して data.json を最新化中…（数分かかることがあります）")
    try:
        cp = subprocess.run(argv, cwd=HERE, env=clean_env(),
                            text=True, timeout=1500)
    except subprocess.TimeoutExpired:
        shutil.copy2(backup, DATA)
        write_result("エラー: claude がタイムアウトしました。data.json はバックアップから復元しました。")
        return 1

    # 3) data.json の妥当性チェック → 壊れていれば復元
    try:
        with open(DATA, encoding="utf-8") as f:
            json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        shutil.copy2(backup, DATA)
        write_result(f"エラー: 更新後の data.json が不正なJSONでした（{e}）。"
                     "バックアップから復元しました。変更は適用していません。")
        return 1

    if cp.returncode != 0:
        # claude 自体が失敗（未ログイン等）。data.json は妥当なので残すが警告。
        if not os.path.exists(RESULT):
            write_result(f"claude が異常終了しました（exit {cp.returncode}）。"
                         "未ログインの可能性: ターミナルで `claude` → `/login` を確認してください。")
        return 1

    if not os.path.exists(RESULT):
        write_result("AI更新は完了しましたが、変更サマリは生成されませんでした。")

    # 5) data.json → Notion 書き戻し（Notionが「正」）＋ pull で正規化
    push_msg = notion_push_safe()
    if push_msg:
        # 結果サマリ末尾に Notion 同期の結果を追記（人が後で確認できるように）
        try:
            with open(RESULT, "a", encoding="utf-8") as f:
                f.write(f"\n---\n{push_msg}\n")
        except OSError:
            pass

    # 6) 変更があれば git コミット（バックアップは作業ツリーから除外）
    changed = git("diff", "--quiet", "--", "data.json").returncode != 0
    if changed:
        git("add", "data.json", "ai_update_result.md")
        c = git("commit", "-m", f"AI更新: data.json をリンク最新化＋Notion同期 ({today})")
        log("変更を git にコミットしました。" if c.returncode == 0
            else f"git commit に失敗: {c.stderr.strip()}")
    else:
        log("data.json に変更はありませんでした。")

    log("完了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
