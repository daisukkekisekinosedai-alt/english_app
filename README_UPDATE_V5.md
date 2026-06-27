# にゃんにゃんイングリッシュ Update v5

## 変更内容

### 4択を同じ品詞から出す

「日本語訳の品詞だけで答えが分かってしまう」問題に対応しました。

例:
- 正解が動詞なら、選択肢も動詞の日本語訳を優先
- 正解が名詞なら、選択肢も名詞の日本語訳を優先
- 正解が形容詞なら、選択肢も形容詞の日本語訳を優先
- 正解が副詞なら、選択肢も副詞の日本語訳を優先

同じ品詞の単語が不足している場合だけ、ランダムに補完します。

## DB変更

words テーブルに以下を追加します。

```text
part_of_speech
```

既存DBに対しては起動時に自動追加されます。
既存単語は日本語訳・英単語・カテゴリから品詞を自動推定して埋めます。

## CSVインポート

以下の列に対応しました。

```text
part_of_speech
pos
品詞
```

指定できる値:

```text
noun / 名詞
verb / 動詞
adjective / 形容詞
adverb / 副詞
other / その他
```

空欄でも自動判定されます。

## Render反映

```powershell
git add .
git commit -m "update same part of speech choices"
git push
```

Renderの自動デプロイがONなら自動反映されます。
手動なら Render → Manual Deploy → Deploy latest commit を押してください。
