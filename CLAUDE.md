# CLAUDE.md — ロングステイ宿データベース

全国の独立系ロングステイ宿（個室あり・長期割・地域交流があり、直予約できる宿）を
検索・絞り込みできる単一ページWebアプリのCLAUDE.md（運用メモ）。
**GitHub Pages公開は廃止し、ローカル（Tailscale経由）運用に切り替え済み**（2026-06-24）。
**データは Notion を「正」、`data.json` はその読み出しキャッシュ**に変更（2026-06-27）。

## 概要・運用方針
- 公開URL（GitHub Pages）は**使わない**。Macでローカルサーバを立て、Tailscale経由で
  iPhone(Brave)等から `http://` でアクセスする。
- gitリポジトリはバックアップ兼バージョン管理として残す（push可）。公開ページとしては使わない。
- **データソースは Notion DB が「正（マスター）」**。`data.json` はそれを `notion_sync.py` で
  書き出したキャッシュで、`index.html` はこの `data.json` を fetch して描画する。
  - 編集は **Notion アプリで行う**のが基本 → ページの「🔄 Notionから取り込み」or サーバ再起動で反映。
  - Notion APIトークンは **`notion_config.json`（gitignore）にサーバ側保管**。ブラウザには出さない。
  - 初回連携の手順は **`NOTION_SETUP.md`** を参照（Integration作成→親ページ接続→`notion_sync.py setup`）。
  - Notion 未設定でも従来どおり `data.json` をそのまま配信して動く（連携は任意の上乗せ）。

## ファイル構成
```
~/services/longstay-db/
├── index.html               … UI本体（data.json を fetch して描画＋メンテボタン）
├── monthly.html             … 【別ツール】住まい検索ランチャー（料金コミコミ・アプリ完結の「エアビー型」中心）
├── monthly.html.bak2        … monthly.html リファクタ前のバックアップ
├── data.json                … 施設データのキャッシュ（37件）。Notion が「正」。直接編集も可だが基本はNotion
├── notion_sync.py           … Notion同期（pull/push/setup）。標準ライブラリのみ・pip不要。★連携の中核
├── notion_config.json       … Notion APIトークン/DB-ID（★gitignore・コミット禁止）
├── notion_config.example.json … 上記の雛形（これをコピーして使う）
├── NOTION_SETUP.md          … Notion連携の初回セットアップ手順書
├── server.py                … ローカルサーバ（静的配信＋更新API＋起動時pull）。標準ライブラリのみ
├── ai_update.py             … AI更新ワーカー（pull→claude編集→Notion書き戻し→pull→commit）
├── check_links.py           … リンク死活チェッカー
├── link_status.json         … check_links.py の生出力（最終チェック日時つき）
├── link_report.md           … 要確認リストのMarkdownレポート
├── ai_update_result.md      … 直近AI更新の変更サマリ（ボタン押下時に生成）
├── start-longstay-db.command… サーバ起動スクリプト（ダブルクリック可）
├── server.log               … サーバのアクセス/エラーログ（gitignore）
├── ai_update.log            … AI更新の実行ログ（gitignore）
├── index.html.bak.YYYYMMDD  … リファクタ前のバックアップ
├── README.md                … 概要・GitHub Pages無効化手順
└── CLAUDE.md                … このファイル
```
- 施設データは以前 index.html にベタ書きだったが、保守性のため **data.json に外出し**した。
  index.html は起動時に `fetch('data.json')` で読む（→ **HTTPサーバ経由必須**。
  `file://` で開くと fetch がブロックされデータが出ない）。

## 別ツール: 住まい検索ランチャー（monthly.html）
同じサーバで配信する**独立した別ページ**（単一HTML・全部インライン・新規外部依存なし）。
`http://100.67.251.19:5055/monthly.html`（index.html 上部からリンクあり）。本体の
「独立系・直予約ゲストハウスDB」とは目的が違い、**料金コミコミでアプリ/オンライン完結の
「住む×泊まる」サービス（=エアビー型）をエリア起点で開く**ためのランチャー。データは持たない純クライアント実装。

> **方針転換の経緯（2026-06-29）**: もとはレオパレス/LIFULL/W&M/グッドマンスリー等の
> **都道府県ディープリンク型ポータル**を新規タブで一斉に開く設計だった。だが「不動産屋を挟む・
> 部屋ごとにルールが違う・賃料と総額が乖離（清掃/光熱の上乗せ）」が嫌で、**Airbnbのように
> 全部コミコミ・アプリで完結**するサービスを主役に作り替えた。旧ポータルと「一斉に開く」機構は撤去済み。

### いまの構成
- **エリア選択**: 注目5エリア（タイル）＋47都道府県プルダウン。`PREFS`/`FEATURED` 配列が slug↔日本語名の対応。
- **メモ**（エリア毎・複数行・自動保存）、**お気に入り**、**全履歴**（slug重複なし・回数つき／
  最近順・回数順トグル／**CSVエクスポート**＝UTF-8 BOM付）、**メモの全文横断検索**。
  履歴は「**エアビー型カードを開いた＝そのエリアを検索した**」として記録する。
- **主役: エアビー型サービス**（定数 `STAY_APPS`）。料金コミコミ・敷礼/仲介/光熱なし・アプリ完結:
  - unito（unito.life）／ Sumyca（www.sumyca.com）／ goodroom サブスくらし（www.goodrooms.jp）… **トップのみ**
  - Airbnbマンスリー … **選択エリア連動**で `https://www.airbnb.jp/s/<エリア名>/homes`（月の絞り込みはアプリ内）
- **他の住まいサービス**（定数 `OTHER_SERVICES`）: ADDress（トップのみ）／自治体お試し移住住宅（選択エリアでGoogle検索）。
- **localStorage キー**: `monthly-launcher-v1`（構造 `{notes,history,favorites,lastSlug,historySort}`。後方互換で追加）。

### 編集ルール（重要）
- **サービス追加/URL変更は `STAY_APPS`・`OTHER_SERVICES` 配列だけを直す**（URLが変わってもここだけ）。
- **URLは推測で作らない＝実機で確認**。都道府県ディープリンクは実在確認できた場合のみ採用。
  （検証メモ: Sumyca `/osaka`・`/shimane` は404＝都道府県スラッグ非対応。goodroomのエリアは
  6大都市圏のみ。→ いずれもトップのみ採用。Airbnb の `/s/<エリア>/homes` は標準形式で採用。）
- **掲載前にサービス生存を確認**。例: NOW ROOM は2024/11/30終了のため不採用。多拠点サブスク
  （ADDress/LivingAnywhere Commons等）は拠点情報が古くなりがち＝載せるならトップ入口に留める。
- 予算・期間・間取りの絞り込みは各サービス側で行う前提（横断で確実に効くパラメータが無いため持たせない）。

## サーバの起動 / 停止
- **起動**: `start-longstay-db.command` をダブルクリック（または
  `bash ~/services/longstay-db/start-longstay-db.command`）。
  - `python3 server.py 5055` を nohup でバックグラウンド起動。二重起動はしない。
  - ログは `server.log`。
- **停止**: `pkill -f 'server.py 5055'`
- **ポート**: `5055`（既存サービス 5050/8090/8501/3000/7799/8787 と非衝突）。
- `server.py` は静的配信に加え、ページの「メンテナンス」ボタン用APIを提供する
  （標準ライブラリのみ・追加インストール不要）。

## ページからの更新（メンテナンスボタン）
ページ下部「🛠 内容のメンテナンス」に3つのボタン。ローカルサーバ経由でのみ動作。
- **🔄 Notionから取り込み** → `POST /api/notion-pull` → `notion_sync.pull()` を実行し、
  Notion DB の内容で `data.json` を上書きして画面を再描画。Notionアプリで編集した後に押す。
  （Notion未設定なら丁寧なエラーを返すだけで他機能は動く）
- **🔗 リンクをチェック** → `POST /api/check-links` → `check_links.py` を実行し、
  要確認リスト（link_report.md）をその場に表示。data.json は変更しない（数秒）。
- **🤖 AIで最新化を依頼** → `POST /api/ai-update` → `ai_update.py` をバックグラウンド起動。
  ローカル `claude` CLI（サブスク=無課金）が点検→各宿をWeb確認→`data.json`を更新→**Notionへ書き戻し**。
  進捗はページがポーリング表示し、完了で自動リロード（数分）。
  - フロー: ①Notion pull(最新化) ②`data.json`バックアップ ③check_links ④claude編集
    ⑤JSON妥当性検証(壊れたら復元) ⑥**Notion push(書き戻し)＋pull(正規化)** ⑦git自動コミット。
  - 安全策: 実行前に `data.json.bak.<日時>` を退避、更新後にJSON妥当性を検証（壊れたら復元）、
    変更があれば **git に自動コミット**（`git revert`/`git checkout` で戻せる）。
    Notion 未設定/到達不可なら書き戻しはスキップし、ローカル更新だけ残す（処理は止めない）。
  - claude には `_notion_id`（同期の鍵）を消すなと明示済み。
  - claude には Bash を渡さず Read/Edit/Write/WebSearch/WebFetch/Grep/Glob のみ許可
    （Web取得先からのプロンプトインジェクションでシェルを叩かせない設計）。
  - **前提**: 一度ターミナルで `claude` → `/login`（Pro/Max。API keyではない）が必要。
    未ログインだとAI更新はエラーになる（`feature_local_claude_subscription` 参照）。
  - AIの変更は**鵜呑みにせず**、完了後にサマリ（ai_update_result.md）を確認すること。
    推測URLが混じる可能性があるため、重要な変更は人手/Claude Codeで裏取りを。

## アクセスURL
- ローカル: `http://localhost:5055/`
- **Tailscale経由（iPhone等）**: `http://100.67.251.19:5055/`
  - Brave等で **http://**（httpsではない）。AC電源時はスリープしない設定済み。

## Notion 同期（notion_sync.py）
Notion が「正」、`data.json` はキャッシュ。同期は標準ライブラリのみの `notion_sync.py` が担う
（pip不要・依存ゼロ。Notion API は urllib で直接叩く）。設定は `notion_config.json`（gitignore）。

```
python3 notion_sync.py setup [親ページID]  # 初回: DB作成＋37件投入（NOTION_SETUP.md 参照）
python3 notion_sync.py pull                # Notion → data.json（キャッシュ更新）
python3 notion_sync.py push                # data.json → Notion（upsert＋不在ページarchive）→pull正規化
python3 notion_sync.py selftest            # 変換ロジックの自己テスト（通信なし）
```

- **プロパティ対応**: name(Title) / pref・region(Select) / tags(Multi-select) /
  loc・body(Rich text) / feat(Checkbox) / order(Number,並び順) /
  **links は Rich text に JSON文字列**（`[["表示名","URL"],...]`）で完全往復。
- **upsert の鍵**: 各レコードの `_notion_id`（NotionページID）。pull で自動付与され data.json に残る。
  無い場合は `name` で突合。`index.html` は `_notion_id` を無視して描画する。
- **server.py 起動時**に best-effort で pull（未設定/到達不可なら既存 data.json を配信）。
- 詳しい初回手順とトラブルシュートは **`NOTION_SETUP.md`**。

## 施設データの編集（基本は Notion アプリ、直接 data.json も可）
**推奨は Notion アプリで編集** → 「🔄 Notionから取り込み」or サーバ再起動で反映。
緊急時は `data.json` を直接編集してもよいが、その場合は `python3 notion_sync.py push` で
Notion に書き戻すこと（さもないと次の pull/起動時pullで上書きされ消える）。
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
- **許容リスト（whitelist）**: 「サイトは生きているがこの環境のDNS等で到達できない」リンクは
  check_links.py 冒頭の `KNOWN_OK`（`URL → 確認メモ`）に登録すると、要確認リストから外れ、
  レポート末尾の「🟡 許容リスト適用」に分けて表示される（見落とし防止）。
  例: `uzuhouse.com`（このMacのDNSで未解決だが営業中）。閉鎖を確認したら登録を外し、通常の
  要確認フローで対応する。

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
