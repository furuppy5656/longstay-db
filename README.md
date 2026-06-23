# ロングステイ宿データベース

全国の独立系ロングステイ宿（個室あり・長期割・地域交流があり、直予約できる宿、約37件）を
フリーワード＋地域＋条件で絞り込める単一ページWebアプリ。

> **このリポジトリは公開ページとしては使いません。**
> GitHub Pages公開は廃止し、ローカル（Mac）でサーバを立てて Tailscale 経由で
> 閲覧するローカル運用に切り替えました（2026-06-24）。
> リポジトリはバックアップ兼バージョン管理として残しています。

## 使い方（ローカル運用）
1. `start-longstay-db.command` をダブルクリックしてサーバ起動（ポート5055）。
2. ブラウザで開く:
   - Mac: `http://localhost:5055/`
   - iPhone等(Brave): `http://100.67.251.19:5055/`（Tailscale経由・**http**）

詳しい運用・データ編集・リンクチェックの手順は [CLAUDE.md](CLAUDE.md) を参照。

## GitHub Pages を無効化する手順（ブラウザ操作）
ローカル運用に切り替えたため、GitHub側のPagesを無効化します（任意・推奨）:

1. ブラウザで GitHub のこのリポジトリ（`furuppy5656/longstay-db`）を開く。
2. 上部タブ **Settings** をクリック。
3. 左サイドバー **Pages** をクリック。
4. **Build and deployment** の **Source** を **`Deploy from a branch`** から
   **`None`** に変更して保存。
   - （`None` が選べない/GitHub Actions運用の場合は、Pages のワークフローを無効化するか
     Pages 環境を削除する。）
5. 数分後 `https://furuppy5656.github.io/longstay-db/` が 404 になれば停止完了。

> Pagesを無効化してもリポジトリ・コミット履歴はそのまま残ります。
> 再公開したくなったら同じ画面で Source を branch に戻すだけです。
