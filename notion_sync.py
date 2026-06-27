#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notion 同期モジュール（標準ライブラリのみ・pip不要）。

構成: **Notion を「正」**、`data.json` をその読み出しキャッシュとする。
  - pull : Notion DB → data.json（index.html はこの data.json を fetch して描画）
  - push : data.json → Notion DB（AI更新の書き戻し。upsert＋data.jsonに無いページのarchive）
  - setup: 親ページ配下に DB を新規作成し、data.json の全件を投入（初回移行）
  - selftest: ネットワーク無しでフィールド⇄プロパティの往復変換を検証

設定ファイル: `notion_config.json`（**gitignore 必須・トークンを含む**）
  {
    "token": "ntn_xxx（Integration の Internal Integration Secret）",
    "database_id": "（setup 後に自動で書き込まれる）",
    "parent_page_id": "（setup 時に DB を作る親ページのID）"
  }
  環境変数 NOTION_TOKEN / NOTION_DATABASE_ID / NOTION_PARENT_PAGE_ID があれば優先。

Notion プロパティ ⇄ data.json フィールド対応:
  | data.json | Notion プロパティ | 型          |
  |-----------|------------------|-------------|
  | name      | name             | Title       |
  | pref      | pref             | Select      |
  | region    | region           | Select      |
  | loc       | loc              | Rich text   |
  | body      | body             | Rich text   |
  | tags      | tags             | Multi-select|
  | feat      | feat             | Checkbox    |
  | (並び順)  | order            | Number      |
  | links     | links            | Rich text（JSON文字列 [["表示名","URL"],...] を格納し完全往復）|
  data.json 側には Notion ページIDを "_notion_id" として持たせ、upsert の鍵にする
  （無ければ name で突き合わせ）。index.html は _notion_id を無視して描画する。

使い方:
  python3 notion_sync.py setup [親ページID]   # DB作成＋全件投入（初回）
  python3 notion_sync.py pull                  # Notion → data.json
  python3 notion_sync.py push                  # data.json → Notion
  python3 notion_sync.py selftest              # 変換ロジックの自己テスト（通信なし）
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "data.json")
CONFIG_PATH = os.path.join(HERE, "notion_config.json")

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# index.html の REGIONS / TAGS と一致させること（Select/Multi-select の初期選択肢）
REGIONS = ["関東", "九州", "中国", "東北", "北陸", "関西", "四国", "沖縄", "甲信越"]
TAGS = ["コワーキング", "個室", "地域交流", "カフェ/コーヒー", "温泉", "古民家",
        "海・島", "月額/長期割", "ADDress連携", "移住体験", "全国チェーン"]

RT_CHUNK = 1900  # Notion rich_text 1要素は最大2000字。安全側で分割。


# ----------------------------------------------------------------------------
# 設定の読み書き
# ----------------------------------------------------------------------------
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    # 環境変数があれば優先
    for key, env in (("token", "NOTION_TOKEN"),
                     ("database_id", "NOTION_DATABASE_ID"),
                     ("parent_page_id", "NOTION_PARENT_PAGE_ID")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def is_configured():
    """pull/push に最低限必要な token と database_id が揃っているか。"""
    cfg = load_config()
    return bool(cfg.get("token") and cfg.get("database_id"))


# ----------------------------------------------------------------------------
# Notion REST 呼び出し（urllib・依存なし）
# ----------------------------------------------------------------------------
def _api(method, path, token, payload=None):
    url = API_BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    last_err = None
    for attempt in range(4):  # 429/5xx は軽くリトライ
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(1.0 + attempt)
                last_err = RuntimeError(f"Notion API {e.code}: {body[:300]}")
                continue
            raise RuntimeError(f"Notion API {e.code} ({method} {path}): {body[:500]}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(1.0 + attempt)
                last_err = RuntimeError(f"Notion API 接続失敗: {e.reason}")
                continue
            raise RuntimeError(f"Notion API 接続失敗 ({method} {path}): {e.reason}")
    raise last_err or RuntimeError("Notion API 呼び出しに失敗しました")


# ----------------------------------------------------------------------------
# 値の変換ヘルパ
# ----------------------------------------------------------------------------
def _rt(text):
    """文字列 → rich_text 配列（2000字制限を超えないよう分割）。"""
    text = text or ""
    if not text:
        return []
    return [{"type": "text", "text": {"content": text[i:i + RT_CHUNK]}}
            for i in range(0, len(text), RT_CHUNK)]


def _plain(prop):
    """rich_text / title プロパティ → 連結プレーン文字列。"""
    if not prop:
        return ""
    arr = prop.get("rich_text") or prop.get("title") or []
    return "".join(t.get("plain_text", t.get("text", {}).get("content", ""))
                   for t in arr)


def _select_name(prop):
    sel = (prop or {}).get("select")
    return sel.get("name", "") if sel else ""


# ----------------------------------------------------------------------------
# data.json レコード ⇄ Notion プロパティ
# ----------------------------------------------------------------------------
def record_to_properties(item, order):
    """data.json の1レコード → Notion ページの properties ペイロード。"""
    props = {
        "name": {"title": _rt(item.get("name", ""))},
        "loc": {"rich_text": _rt(item.get("loc", ""))},
        "body": {"rich_text": _rt(item.get("body", ""))},
        "tags": {"multi_select": [{"name": t} for t in item.get("tags", [])]},
        "feat": {"checkbox": bool(item.get("feat"))},
        "order": {"number": order},
        "links": {"rich_text": _rt(json.dumps(item.get("links", []),
                                              ensure_ascii=False))},
    }
    # Select は値が空なら None（クリア）
    props["pref"] = {"select": {"name": item["pref"]}} if item.get("pref") else {"select": None}
    props["region"] = {"select": {"name": item["region"]}} if item.get("region") else {"select": None}
    return props


def page_to_record(page):
    """Notion ページ → (order, data.json レコード)。"""
    p = page.get("properties", {})
    rec = {
        "name": _plain(p.get("name")),
        "pref": _select_name(p.get("pref")),
        "region": _select_name(p.get("region")),
        "loc": _plain(p.get("loc")),
        "tags": [o["name"] for o in (p.get("tags", {}).get("multi_select") or [])],
        "body": _plain(p.get("body")),
    }
    links_raw = _plain(p.get("links"))
    try:
        rec["links"] = json.loads(links_raw) if links_raw else []
    except json.JSONDecodeError:
        rec["links"] = []
    if (p.get("feat", {}) or {}).get("checkbox"):
        rec["feat"] = True
    rec["_notion_id"] = page.get("id")
    order = (p.get("order", {}) or {}).get("number")
    return (order if order is not None else 1e9), rec


# ----------------------------------------------------------------------------
# 高水準オペレーション
# ----------------------------------------------------------------------------
def _query_all_pages(token, database_id):
    """DB の全ページをページネーションで取得（order 昇順ソート要求）。"""
    pages, cursor = [], None
    while True:
        payload = {"page_size": 100,
                   "sorts": [{"property": "order", "direction": "ascending"}]}
        if cursor:
            payload["start_cursor"] = cursor
        res = _api("POST", f"/databases/{database_id}/query", token, payload)
        pages.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return pages


def pull(write=True):
    """Notion DB → data.json（キャッシュ更新）。書き出した件数を返す。"""
    cfg = load_config()
    if not (cfg.get("token") and cfg.get("database_id")):
        raise RuntimeError("notion_config.json に token と database_id が必要です。"
                           "未設定なら setup を先に実行してください。")
    pages = _query_all_pages(cfg["token"], cfg["database_id"])
    decorated = [page_to_record(pg) for pg in pages]
    decorated.sort(key=lambda x: x[0])
    records = [rec for _, rec in decorated]
    if write:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
            f.write("\n")
    return len(records)


def push():
    """data.json → Notion DB。upsert（_notion_id→name の順で突合）＋
    data.json に無いページは archive。{created, updated, archived} を返す。
    push 後に data.json を pull で正規化（_notion_id / order を確定）する。"""
    cfg = load_config()
    if not (cfg.get("token") and cfg.get("database_id")):
        raise RuntimeError("notion_config.json に token と database_id が必要です。")
    token, db = cfg["token"], cfg["database_id"]

    with open(DATA_PATH, encoding="utf-8") as f:
        records = json.load(f)

    existing = _query_all_pages(token, db)
    by_id = {pg["id"]: pg for pg in existing}
    by_name = {}
    for pg in existing:
        by_name.setdefault(_plain(pg["properties"].get("name")), pg["id"])

    used_ids, created, updated = set(), 0, 0
    for i, rec in enumerate(records):
        props = record_to_properties(rec, i)
        pid = rec.get("_notion_id")
        if pid not in by_id:                       # 鍵IDが無効なら name で再突合
            pid = by_name.get(rec.get("name", ""))
        if pid and pid in by_id:
            _api("PATCH", f"/pages/{pid}", token, {"properties": props})
            updated += 1
            used_ids.add(pid)
        else:
            res = _api("POST", "/pages", token,
                       {"parent": {"database_id": db}, "properties": props})
            rec["_notion_id"] = res["id"]
            used_ids.add(res["id"])
            created += 1

    archived = 0
    for pid in by_id:
        if pid not in used_ids:
            _api("PATCH", f"/pages/{pid}", token, {"archived": True})
            archived += 1

    return {"created": created, "updated": updated, "archived": archived}


def create_database(token, parent_page_id, title="ロングステイ宿データベース"):
    """親ページ配下に DB を新規作成し、database_id を返す。"""
    schema = {
        "name": {"title": {}},
        "pref": {"select": {}},
        "region": {"select": {"options": [{"name": r} for r in REGIONS]}},
        "tags": {"multi_select": {"options": [{"name": t} for t in TAGS]}},
        "loc": {"rich_text": {}},
        "body": {"rich_text": {}},
        "links": {"rich_text": {}},
        "feat": {"checkbox": {}},
        "order": {"number": {}},
    }
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": schema,
    }
    res = _api("POST", "/databases", token, payload)
    return res["id"]


def setup(parent_page_id=None):
    """DB を新規作成し data.json 全件を投入。database_id を config に保存。"""
    cfg = load_config()
    token = cfg.get("token")
    if not token:
        raise RuntimeError(
            "notion_config.json に token がありません。\n"
            "  1) https://www.notion.so/my-integrations で Integration を作成\n"
            "  2) Internal Integration Secret（ntn_...）を notion_config.json の token に記入\n"
            "  3) DB を作りたい Notion ページを開き「…」→ 接続 → 作った Integration を追加\n"
            "  4) そのページのIDを parent_page_id に記入（URL末尾の32桁）")
    parent = parent_page_id or cfg.get("parent_page_id")
    if not parent:
        raise RuntimeError("親ページIDが必要です: "
                           "`python3 notion_sync.py setup <親ページID>` か "
                           "notion_config.json の parent_page_id を設定してください。")

    db_id = create_database(token, parent)
    cfg["database_id"] = db_id
    cfg["parent_page_id"] = parent
    save_config(cfg)
    print(f"✅ Notion DB を作成しました: database_id={db_id}")

    summary = push()  # data.json の全件を投入
    print(f"✅ data.json を投入: 新規 {summary['created']} 件")
    pull()            # _notion_id / order を data.json に反映
    print("✅ data.json を Notion 内容で正規化しました（_notion_id 付与）。")
    return db_id


# ----------------------------------------------------------------------------
# 自己テスト（通信なし）: 往復変換が一致するか
# ----------------------------------------------------------------------------
def selftest():
    sample = {
        "name": "テスト宿",
        "pref": "茨城",
        "region": "関東",
        "loc": "水戸市柳町（水戸駅圏）",
        "tags": ["コワーキング", "地域交流"],
        "body": "本文" * 1000,  # 2000字超で分割を確認
        "links": [["公式サイト", "https://example.com"], ["Instagram", "https://example.com/ig"]],
        "feat": True,
    }
    props = record_to_properties(sample, 3)

    # Notion から返るページ形を擬似生成（plain_text を埋める）
    def to_plain_arr(rich):
        return [{"plain_text": t["text"]["content"]} for t in rich]

    fake_page = {
        "id": "page-123",
        "properties": {
            "name": {"title": to_plain_arr(props["name"]["title"])},
            "pref": {"select": props["pref"]["select"]},
            "region": {"select": props["region"]["select"]},
            "loc": {"rich_text": to_plain_arr(props["loc"]["rich_text"])},
            "body": {"rich_text": to_plain_arr(props["body"]["rich_text"])},
            "tags": {"multi_select": props["tags"]["multi_select"]},
            "feat": {"checkbox": props["feat"]["checkbox"]},
            "links": {"rich_text": to_plain_arr(props["links"]["rich_text"])},
            "order": {"number": props["order"]["number"]},
        },
    }
    order, rec = page_to_record(fake_page)
    assert order == 3, order
    assert rec["_notion_id"] == "page-123"
    for k in ("name", "pref", "region", "loc", "tags", "body", "links", "feat"):
        assert rec[k] == sample[k], f"不一致: {k}: {rec[k]!r} != {sample[k]!r}"
    # data.json に実在するレコードでも往復が壊れないか
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for it in data:
            p = record_to_properties(it, 0)
            assert _plain({"rich_text": p["links"]["rich_text"]}) == \
                json.dumps(it.get("links", []), ensure_ascii=False)
        print(f"✅ selftest OK（サンプル往復＋data.json {len(data)} 件の links 往復）")
    else:
        print("✅ selftest OK（サンプル往復。data.json は未配置）")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "setup":
        setup(argv[2] if len(argv) > 2 else None)
    elif cmd == "pull":
        n = pull()
        print(f"✅ Notion → data.json: {n} 件を書き出しました。")
    elif cmd == "push":
        s = push()
        n = pull()
        print(f"✅ data.json → Notion: 新規 {s['created']} / 更新 {s['updated']} "
              f"/ アーカイブ {s['archived']}（→ pull で {n} 件に正規化）")
    elif cmd == "selftest":
        selftest()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
