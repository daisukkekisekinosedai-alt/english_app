# にゃんにゃんイングリッシュ v17 hotfix

## 修正内容

v17反映後に内部サーバーエラーが出る可能性があったため、
Render/Jinja環境で落ちやすいテンプレート記法を安全寄りに修正しました。

## 修正したこと

- テンプレート内の `url_for(feature.route)` を廃止
- `feature_href(feature.id)` 経由に変更
- テンプレート内スライス `top_words[:5]` を廃止
- Python側で `top_words` を事前に作る方式へ変更
- `/debug/features` を追加
  - 有効な機能番号を確認できます

## 機能番号

- 1: スマート学習エンジン
- 2: 集中モード
- 3: 今日の学習計画
- 4: 試験モード
- 5: ミスノート

## 1,4,5だけ使う場合

Render の Environment Variables に追加:

```text
ENABLED_FEATURES=1,4,5
```

## 反映

```powershell
git add .
git commit -m "hotfix modular learning suite"
git push
```
