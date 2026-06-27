# にゃんにゃんイングリッシュ v17 hotfix2

## 修正内容

ミスノートに行けない問題を修正しました。

## 対応

- `/mistakes` を常に開けるように変更
- 機能フラグ `ENABLED_FEATURES` の設定に関係なく、URL直打ちならミスノートを開けるように変更
- 下部ナビの「ミス」を常時表示
- 古い/揺れたURL向けに別名ルートを追加

## 追加したURL

```text
/mistakes
/mistake
/miss
/miss-note
/mistake-note
```

## 反映

```powershell
git add .
git commit -m "fix mistake notebook navigation"
git push
```
