# にゃんにゃんイングリッシュ v17 hotfix3

## 修正内容

`missnote` / `ミスノート` が見れない問題をさらに修正しました。

## 対応

- `/missnote` を正式に追加
- `/missnotebook` も追加
- `/mistakenote` も追加
- `/mistakenotebook` も追加
- `/mistakes` も引き続き利用可能
- 下部ナビの「ミス」は `/missnote` に固定
- ミスノート取得SQLを安全寄りに変更
- ミスノート取得でエラーが出ても画面自体は表示するように変更

## 使えるURL

```text
/missnote
/missnotebook
/miss-note
/miss-notebook
/miss_note
/mistakes
/mistake
/mistakenote
/mistakenotebook
/mistake-note
/mistake-notebook
/mistake_note
```

## 反映

```powershell
git add .
git commit -m "fix missnote route and notebook loading"
git push
```
