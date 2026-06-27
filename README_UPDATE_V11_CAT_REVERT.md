# にゃんにゃんイングリッシュ v11 猫画像差し戻し版

## 変更内容

v11で差し替えた猫画像が不評だったため、
**最初の猫画像（v7時点の猫）に戻した版**です。

## 維持される内容

- アプリ名「にゃんにゃんイングリッシュ」
- にゃんコーチ機能
- 猫の部屋
- ユーザー情報
- 単語データ
- 学習履歴

## 差し戻した画像

- cat-neutral.png
- cat-play.png
- cat-rest.png
- cat-sad.png
- cat-sleepy.png
- cat-study.png

## DB変更

なし。

## Render反映

```powershell
git add .
git commit -m "revert cat images to original"
git push
```
