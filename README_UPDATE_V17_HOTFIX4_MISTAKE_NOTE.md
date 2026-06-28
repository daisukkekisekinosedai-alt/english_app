# にゃんにゃんイングリッシュ v17 hotfix4

## 修正内容

`/mistake-note` が見れない問題に対する専用修正版です。

## 対応

- `/mistake-note` を専用ルートとして分離
- `/mistake-note` は安全表示用テンプレート `mistakes_safe.html` を使用
- 通常の `/missnote` 画面で落ちる場合でも、`/mistake-note` は開けるように変更
- 下部ナビの「ミス」も `/mistake-note` に固定
- `/mistake-note-health` を追加
  - ブラウザで開いて `mistake-note route ok` と出ればルート登録は成功

## 確認URL

```text
/mistake-note-health
/mistake-note
```

## 反映

```powershell
git add .
git commit -m "fix mistake note direct page"
git push
```
