# にゃんにゃんイングリッシュ v17 hotfix5

## 修正内容

`/mistake-note` の Internal Server Error の原因を修正しました。

## 原因

Jinjaテンプレートで以下のように書いていました。

```jinja
notebook.items
```

しかし `notebook` はPythonのdictなので、Jinjaでは `"items"` キーではなく
dictの `.items()` メソッドとして解釈されることがあります。

その結果、ミス単語一覧をループする箇所で例外になり、Internal Server Error になっていました。

## 修正

以下のように、キー指定へ変更しました。

```jinja
notebook["items"]
```

同様に、以下も明示的なキー指定へ修正しました。

- `notebook["total"]`
- `notebook["high_count"]`
- `notebook["recent_count"]`

## 追加

診断用URLを追加しました。

```text
/mistake-note-raw
```

これはテンプレートをほぼ使わず、ミスノートの中身を最低限のHTMLで表示します。

## 確認URL

```text
/mistake-note-health
/mistake-note-raw
/mistake-note
```

## 反映

```powershell
git add .
git commit -m "fix mistake note template dict access"
git push
```
