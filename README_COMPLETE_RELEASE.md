# English Pocket Complete Release v2

最新版の完全版です。

## 入っているもの

- 英単語学習Webアプリ
- ユーザー登録 / ログイン
- プロフィール
- ピンク猫UI
- リアル寄り猫画像
- 正解 / 不正解に応じた猫表示
- ランキング画面改善版
- 10問クイズ
- リスニング
- 音声生成
- TOEICカテゴリ別モード
- 復習モード
- バッジ / レベル / ストリーク
- Render公開用設定

## ローカル起動

```powershell
cd C:\Users\81806\python\english_pocket_complete_release_v2
pip install -r requirements.txt
python app.py
```

ブラウザで開く:

```text
http://127.0.0.1:5000
```

## Render公開

GitHubに中身をアップロードして、RenderでBlueprintとして読み込めます。

必要ファイル:

- app.py
- requirements.txt
- Procfile
- render.yaml
- .python-version
- templates/
- static/

Renderでは `render.yaml` に以下を設定済みです。

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- DATA_DIR: `/var/data`
- DB_PATH: `/var/data/english.db`
- Persistent Disk: `/var/data`

## 注意

公式リリースでユーザーデータを消したくない場合は、RenderのPersistent Disk付きプラン推奨です。
無料プランだと、SQLite DBやアップロード画像が消える可能性があります。
