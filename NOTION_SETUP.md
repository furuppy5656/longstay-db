# Notion 連携セットアップ手順

このDBは **Notion を「正（マスター）」**、`data.json` を読み出しキャッシュとする構成です。
初回だけ以下を行えば、以後は Notion で編集 → ページの「🔄 Notionから取り込み」で反映できます。
**トークンはブラウザに出さず、サーバ側（`notion_config.json`）にのみ保管**します。

---

## あなたが手でやる作業（5分）

### 1. Integration（APIトークン）を作る
1. https://www.notion.so/my-integrations を開く →「New integration」
2. 名前は任意（例: `longstay-db`）。Type は **Internal**。
3. 作成後の「Internal Integration Secret」(`ntn_...` で始まる文字列) をコピー。

### 2. DBを作る親ページを用意して Integration を接続
1. Notion で適当なページを1つ作る（例: 「ロングステイ宿DB」）。ここに DB が作られます。
2. そのページ右上「…」→ **「接続」(Connections)** → 手順1で作った Integration を追加。
   （これをしないと API からそのページに書けません）
3. そのページの **ID** を控える＝ページURLの末尾32桁の16進。
   例 `https://www.notion.so/My-Page-**2f1c8a9b4d5e4f6a8b1c2d3e4f5a6b7c**` の太字部分。
   （ハイフン無し32桁。URLに `?` があればその手前まで）

### 3. 設定ファイルに貼る
`notion_config.example.json` を `notion_config.json` にコピーして、token と parent_page_id を記入:

```bash
cd ~/services/longstay-db
cp notion_config.example.json notion_config.json
# notion_config.json をエディタで開き token と parent_page_id を記入（database_id は空のままでOK）
```

`notion_config.json` は `.gitignore` 済み＝**git にはコミットされません**（トークン保護）。

---

## ここから先は自動（DB作成＋37件投入）

```bash
cd ~/services/longstay-db
python3 notion_sync.py setup
```

これで:
- 親ページ配下に DB「ロングステイ宿データベース」を作成（プロパティは自動設定）
- `data.json` の37件を Notion に投入
- `data.json` を Notion 内容で正規化（各レコードに `_notion_id` を付与）
- `database_id` を `notion_config.json` に自動保存

完了後、サーバを再起動すると起動時に Notion から pull します:
```bash
pkill -f 'server.py 5055'; bash start-longstay-db.command
```

---

## 動作確認

```bash
python3 notion_sync.py pull   # Notion → data.json（件数が出ればOK）
```
ブラウザで `http://localhost:5055/`（iPhoneは `http://100.67.251.19:5055/`）を開き、
下部「🛠 内容のメンテナンス」の **🔄 Notionから取り込み** を押して件数が出れば連携成功です。

---

## プロパティ対応表（Notion DB の列）

| Notion プロパティ | 型 | data.json フィールド |
|---|---|---|
| name | タイトル | name |
| pref | セレクト | pref（都道府県／全国チェーンは「全国」） |
| region | セレクト | region（関東/九州/中国/東北/北陸/関西/四国/沖縄/甲信越） |
| tags | マルチセレクト | tags |
| loc | テキスト | loc |
| body | テキスト | body |
| links | テキスト | links（`[["表示名","URL"],...]` の **JSON文字列**で保持） |
| feat | チェックボックス | feat（★基準・注目枠） |
| order | 数値 | 並び順（小さいほど上。pull時にこの順で並ぶ） |

- **links だけは JSON 文字列**で1セルに入ります。Notion で編集するときは
  `[["公式サイト","https://example.com"]]` の形を崩さないこと（崩れたら pull 時に空配列扱い）。
  公式リンクが死んでいても、各カードの「📍 Googleマップで見る」は `name`＋`loc` から
  index.html が自動生成するので場所確認はできます。
- 新しい施設は Notion で行を追加 → `🔄 Notionから取り込み`。`order` は空でも末尾に並びます。

## トラブルシュート
- `setup` で 401 → token が違う。`ntn_` で始まる Internal Integration Secret か確認。
- `setup` で 404（親ページ）→ 手順2の「接続」を忘れているか parent_page_id が違う。
- pull/push が「未設定」エラー → `notion_config.json` の token と database_id を確認。
