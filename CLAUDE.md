# CLAUDE.md — ロングステイ宿データベース

全国の独立系ロングステイ宿（個室あり・長期割・地域交流があり、直予約できる宿）を
検索・絞り込みできる単一ページWebアプリのCLAUDE.md（運用メモ）。
**GitHub Pages公開は廃止し、ローカル（Tailscale経由）運用に切り替え済み**（2026-06-24）。

## 概要・運用方針
- 公開URL（GitHub Pages）は**使わない**。Macでローカルサーバを立て、Tailscale経由で
  iPhone(Brave)等から `http://` でアクセスする。
- gitリポジトリはバックアップ兼バージョン管理として残す（push可）。公開ページとしては使わない。

## ファイル構成
```
~/services/longstay-db/
├── index.html               … UI本体（data.json を fetch して描画）
├── data.json                … 施設データ（37件）。★編集対象はここ
├── check_links.py           … リンク死活チェッカー
├── link_status.json         … check_links.py の生出力（最終チェック日時つき）
├── link_report.md           … 要確認リストのMarkdownレポート
├── start-longstay-db.command… サーバ起動スクリプト（ダブルクリック可）
├── server.log               … サーバのアクセス/エラーログ
├── index.html.bak.YYYYMMDD  … リファクタ前のバックアップ
├── README.md                … 概要・GitHub Pages無効化手順
└── CLAUDE.md                … このファイル
```
- 施設データは以前 index.html にベタ書きだったが、保守性のため **data.json に外出し**した。
  index.html は起動時に `fetch('data.json')` で読む（→ **HTTPサーバ経由必須**。
  `file://` で開くと fetch がブロックされデータが出ない）。

## サーバの起動 / 停止
- **起動**: `start-longstay-db.command` をダブルクリック（または
  `bash ~/services/longstay-db/start-longstay-db.command`）。
  - `python3 -m http.server 5055` を nohup でバックグラウンド起動。二重起動はしない。
  - ログは `server.log`。
- **停止**: `pkill -f 'http.server 5055'`
- **ポート**: `5055`（既存サービス 5050/8090/8501/3000/7799/8787 と非衝突）。

## アクセスURL
- ローカル: `http://localhost:5055/`
- **Tailscale経由（iPhone等）**: `http://100.67.251.19:5055/`
  - Brave等で **http://**（httpsではない）。AC電源時はスリープしない設定済み。

## 施設データ（data.json）の編集
配列の各要素が1施設。スキーマ:

| フィールド | 型 | 意味 |
|---|---|---|
| `name`  | string | 施設名（必須） |
| `pref`  | string | 都道府県（チップ「県」表示。全国チェーンは `"全国"`） |
| `region`| string | 地域。**許容値**（地域チップと一致させる） |
| `loc`   | string | 所在地の説明（先頭の市区町村からGoogleマップ検索リンクを自動生成） |
| `tags`  | string[] | 条件タグ。**許容値**（条件チップと一致させる） |
| `body`  | string | 紹介本文 |
| `links` | [label,url][] | 公式/紹介リンク。`["表示名","URL"]` の配列。URLを `"#"` にするとリンクなし表示 |
| `feat`  | boolean | （任意）`true` で「★基準・注目」枠＋先頭表示 |

- **region 許容値**: `関東 / 九州 / 中国 / 東北 / 北陸 / 関西 / 四国 / 沖縄 / 甲信越`
  （index.html の `REGIONS` と一致させること。新地域を足すなら両方に追加）
- **tags 許容値**: `コワーキング / 個室 / 地域交流 / カフェ/コーヒー / 温泉 / 古民家 /
  海・島 / 月額/長期割 / ADDress連携 / 移住体験 / 全国チェーン`
  （index.html の `TAGS` と一致させること。チップに出したいタグだけ TAGS に載る）
- **Googleマップリンクは持たせない**。`index.html` の `mapsUrl()` が
  `name` ＋ `loc`先頭の市区町村（無ければ `pref`）から都度生成し、各カードに
  「📍 Googleマップで見る」を必ず付ける。公式リンクが死んでいても現存確認できる。
- 編集後はサーバ再起動不要。**ブラウザを再読込**するだけで反映（`fetch` は no-store）。

## リンクチェックの実行とレポートの読み方
```
cd ~/services/longstay-db
python3 check_links.py
```
- `data.json` の全リンクに GET でアクセスし、`link_status.json`（生データ）と
  `link_report.md`（要確認のみ）を出力。
- レポートには到達不可/4xx・5xx のリンクを持つ施設だけが載る。
  - `403/429`：bot ブロックで実際は生きていることが多い（要・目視）。
  - `到達不可 / 404`：URL変更・閉鎖の可能性が高い。
- **休業の有無はHTTPでは判定不能**。各施設のGoogleマップリンク（レポートに記載）と
  公式を見て確認する。

## リンク切れ・休業を Claude Code で更新する手順
1. `python3 check_links.py` を実行。
2. `link_report.md` を開いて「要確認」施設を把握。
3. 各施設の 📍マップリンク／公式URL を開き、現存・営業・新URLを確認
   （WebFetch / WebSearch、必要なら computer-use でブラウザ確認）。
4. `data.json` を修正:
   - URL変更 → `links` のURLを差し替え。
   - リンク切れだが施設は健在 → マップで足りるなら該当linkを削除。
   - 休業/閉鎖 → `body` に注記、または施設要素ごと削除。
5. `git add -A && git commit -m "リンク更新: <施設名>"`（バックアップ）。必要なら `git push`。
6. サーバは**再起動不要**。ブラウザ再読込のみで反映。

## git運用（バックアップ）
- 変更したら commit / push でバックアップ。remote(origin)はGitHub。
- 公開用ではないので Pages は無効（README参照）。`server.log` `link_status.json` 等の
  生成物はコミットしてもよいが、ノイズになるなら `.gitignore` 対象にしてよい。
