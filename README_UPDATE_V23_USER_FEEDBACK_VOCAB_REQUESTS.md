# にゃんにゃんイングリッシュ v23 User Feedback + Vocabulary Requests

## 追加/修正内容

ユーザー様からの感想をもとに、以下を修正しました。

## 1. おすすめ10問の偏り修正

### 課題

おすすめ10問で以下の問題がありました。

- a,b,c順のように似た並びになる
- 同じような単語が連続する
- 過去形・派生語ばかり出る
- 実質的に学べる語彙数が少なく感じる

### 修正

- スコア順 + 英単語順の固定をやめる
- bucketごとに候補を広めに取得
- word family を簡易判定
- 同じ語幹の単語が固まりすぎないように分散
- category も少し分散
- smartモードでは候補が少ない場合でも同じ単語で水増ししない

---

## 2. 単語改善依頼ボタン

### 追加URL

```text
/words/<word_id>/improve
```

### できること

ユーザーは出題中/結果画面から「この単語を改善依頼」を押せます。

理由:

- 似た単語・過去形/派生語が多い
- 日本語訳がおかしい
- 例文がおかしい
- TOEIC学習に不要そう
- 簡単すぎる
- 難しすぎる/マニアックすぎる
- その他

### 重要仕様

改善依頼が送られた単語は、masterが対応するまで通常ユーザーの問題に出ません。

---

## 3. master用 改善依頼監視画面

### 追加URL

```text
/admin/word-reports
/admin/word-reports/<report_id>
```

masterだけ閲覧できます。

できること:

- open / resolved / rejected 切り替え
- 報告理由確認
- 報告詳細確認
- 対象単語の編集画面へ移動
- 修正済みにして出題再開
- 却下して出題再開

---

## 4. 追加してほしい単語リクエスト

### 追加URL

```text
/word-request
```

ユーザーが追加してほしい単語やカテゴリ要望を送れます。

---

## 5. master用 単語リクエスト確認画面

### 追加URL

```text
/admin/vocab-requests
```

masterだけ閲覧できます。

できること:

- open / added / rejected 切り替え
- ユーザーの要望確認
- 対応メモ入力
- 追加済み/却下に変更

---

## DB変更

### 追加テーブル

```sql
word_improvement_reports
vocab_requests
```

既存の単語・ユーザー・学習履歴は削除されません。

## 反映

```powershell
git add .
git commit -m "add word improvement reports and vocab requests"
git push
```
