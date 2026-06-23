#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ロングステイ宿データベース リンク死活チェッカー

data.json の各施設の公式/紹介リンクに HTTP アクセスし、到達可否・ステータスを
判定して link_status.json に出力。怪しいものを link_report.md にまとめる。

使い方:
    python3 check_links.py

注意:
  - HTTP の死活までしか分からない。「休業しているが Web は生きている」ケースは
    検出できないため、レポートの「要・人手/AI確認」欄を Claude Code で開いて確認し、
    data.json を更新する運用にする（手順は CLAUDE.md 参照）。
  - Googleマップリンクは name+loc から都度生成しているためチェック対象外
    （リンク切れの概念がない）。
"""

import json
import os
import sys
import datetime
import urllib.request
import urllib.error
import ssl

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "data.json")
STATUS_PATH = os.path.join(HERE, "link_status.json")
REPORT_PATH = os.path.join(HERE, "link_report.md")

TIMEOUT = 12  # 秒
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# --- 許容リスト（whitelist）---
# 「HTTPでは到達不可/4xxになるが、Googleマップや別ソースで現存・営業を確認済み」の
# リンク。要確認リストからは除外し、レポート末尾に「許容リスト適用」として残す。
# 例: このMac環境のDNS事情で uzuhouse.com が解決できないが、サイト自体は営業中。
# URL（完全一致）→ 確認メモ（最終確認日と理由）を書く。確認できなくなったら消す。
KNOWN_OK = {
    "https://uzuhouse.com/":
        "2026-06-24確認: 営業中（tabelog/公式en/Instagram）。この環境のDNSで未解決のみ。",
}

# 一部サイトは証明書検証で弾かれるが「到達はできている」ので、
# 死活判定では緩めの SSL コンテキストも使う。
_LAX_SSL = ssl.create_default_context()
_LAX_SSL.check_hostname = False
_LAX_SSL.verify_mode = ssl.CERT_NONE


def maps_query(item):
    """index.html と同じロジックで Googleマップ検索 URL を作る（レポート用）。"""
    import urllib.parse
    loc = item.get("loc", "") or ""
    head = loc
    for sep in ["・", "（", "(", "/"]:
        head = head.split(sep)[0]
    head = head.strip()
    q = (item.get("name", "") + " " + (head or item.get("pref", ""))).strip()
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(q)


def fetch(url):
    """URL に GET でアクセスし (ok, status, note) を返す。"""
    headers = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
    for ctx in (None, _LAX_SSL):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
                code = r.getcode()
                return (200 <= code < 400, code, "ok")
        except urllib.error.HTTPError as e:
            # 405 等は HEAD/GET 非対応だが生存しているとみなす境界。
            # 4xx/5xx はステータスを記録（403 は bot 弾きの可能性、後述レポートで要確認）。
            return (e.code in (401, 403, 405, 406, 429), e.code, f"HTTPError {e.code}")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            # 証明書エラーなら緩い ctx で再試行（ループ継続）
            if "CERTIFICATE" in str(reason).upper() and ctx is None:
                continue
            return (False, None, f"URLError: {reason}")
        except Exception as e:  # noqa: BLE001
            return (False, None, f"{type(e).__name__}: {e}")
    return (False, None, "unreachable")


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    results = []
    suspicious = []   # 要確認施設
    whitelisted = []  # 許容リスト適用で除外したリンク（見落とし防止に記録）

    total_links = 0
    for item in data:
        name = item.get("name", "")
        link_results = []
        item_has_problem = False
        for label, url in item.get("links", []):
            if not url or url == "#":
                continue
            total_links += 1
            ok, status, note = fetch(url)
            wl = url in KNOWN_OK
            flag = "OK " if ok else ("WL " if wl else "NG ")
            print(f"[{flag}] {status if status is not None else '---':>4}  {name} / {label}  {url}")
            lr = {
                "label": label, "url": url,
                "ok": ok, "status": status, "note": note,
                "whitelisted": wl,
                "whitelist_note": KNOWN_OK.get(url, ""),
            }
            link_results.append(lr)
            is_bad = (not ok or (status is not None and status >= 400))
            if is_bad and wl:
                # 許容リスト適用：要確認には載せず、別枠で記録
                whitelisted.append({"name": name, "label": label, "url": url,
                                    "status": status, "note": note,
                                    "whitelist_note": KNOWN_OK[url]})
            elif is_bad:
                item_has_problem = True

        results.append({
            "name": name,
            "pref": item.get("pref", ""),
            "loc": item.get("loc", ""),
            "links": link_results,
        })
        if item_has_problem:
            suspicious.append({
                "name": name,
                "pref": item.get("pref", ""),
                "loc": item.get("loc", ""),
                "maps": maps_query(item),
                "links": link_results,
            })

    status_doc = {
        "checked_at": now,
        "total_facilities": len(data),
        "total_links": total_links,
        "suspicious_count": len(suspicious),
        "whitelisted_count": len(whitelisted),
        "whitelisted": whitelisted,
        "results": results,
    }
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump(status_doc, f, ensure_ascii=False, indent=2)

    # ---- Markdown レポート ----
    lines = []
    lines.append("# リンク死活レポート（ロングステイ宿DB）")
    lines.append("")
    lines.append(f"- 最終チェック: **{now}**")
    lines.append(f"- 施設数: {len(data)} / チェックしたリンク: {total_links}")
    lines.append(f"- 要確認の施設: **{len(suspicious)} 件**"
                 + (f" / 許容リスト適用: {len(whitelisted)} 件" if whitelisted else ""))
    lines.append("")
    lines.append("> HTTPで届かなかった/4xx・5xxを返したリンクを持つ施設のみ掲載。")
    lines.append("> 403/429 等は bot ブロックで実際は生きていることも多い。")
    lines.append("> **休業の有無はHTTPでは分からない**ため、下記をGoogleマップ／公式で確認し、")
    lines.append("> 必要なら data.json を修正してください（手順は CLAUDE.md）。")
    lines.append("")

    if not suspicious:
        lines.append("✅ すべてのリンクが到達可能でした。要対応はありません。")
    else:
        for s in suspicious:
            lines.append(f"## {s['name']}（{s['pref']} / {s['loc']}）")
            lines.append("")
            lines.append(f"- 📍 マップで現存確認: {s['maps']}")
            for lr in s["links"]:
                mark = "✅" if lr["ok"] else "❌"
                st = lr["status"] if lr["status"] is not None else "到達不可"
                lines.append(f"- {mark} [{lr['label']}]({lr['url']}) — `{st}` {lr['note']}")
            lines.append("")
            lines.append("  → 確認後の対応例: URLを新しい公式に差し替え / リンク削除 / "
                         "休業なら body に注記 or 施設ごと削除。")
            lines.append("")

    # 許容リスト（whitelist）適用分：要確認には載せないが、見落とし防止に列挙
    if whitelisted:
        lines.append("---")
        lines.append("")
        lines.append("## 🟡 許容リスト適用（HTTP未到達だが現存確認済み・対応不要）")
        lines.append("")
        lines.append("> check_links.py の `KNOWN_OK` に登録済み。サイトは生きているが"
                     "この環境のDNS事情等で到達できないもの。確認できなくなったら登録を外すこと。")
        lines.append("")
        for w in whitelisted:
            st = w["status"] if w["status"] is not None else "到達不可"
            lines.append(f"- 🟡 {w['name']} / [{w['label']}]({w['url']}) — `{st}` "
                         f"／ {w['whitelist_note']}")
        lines.append("")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("")
    print(f"→ {STATUS_PATH}")
    print(f"→ {REPORT_PATH}")
    print(f"要確認: {len(suspicious)} 件 / 許容リスト適用: {len(whitelisted)} 件 / 全 {len(data)} 施設")
    return 0


if __name__ == "__main__":
    sys.exit(main())
