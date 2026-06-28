# にゃんにゃんイングリッシュ v20 CSV Import Batches

## 追加したこと

CSVアップロード履歴を管理し、あとから特定のアップロード分だけ削除できるようにしました。

## できること

### 1. CSV取り込みごとにバッチIDを発行

CSVをアップロードすると、以下のように管理されます。

```text
Batch 1
Batch 2
Batch 3
```

各単語に `import_batch_id` を持たせるので、
どのCSVで追加された単語か追跡できます。

---

### 2. CSV取り込み履歴画面

URL:

```text
/admin/import-batches
```

master専用です。

表示内容:

- バッチID
- ファイル名
- 追加件数
- 現在残っている単語数
- 重複スキップ件数
- 無効行数
- 取り込み日時
- 実行者
- 状態 active / deleted

---

### 3. 特定CSVだけ削除

例:

```text
Batch 1: 残す
Batch 2: 削除
Batch 3: 残す
```

このような操作ができます。

削除対象:

- そのCSVで追加された単語
- その単語に紐づく学習履歴
- その単語に紐づくお気に入り

削除されないもの:

- 別CSVで追加した単語
- 手入力した単語
- 旧データ
- 他のテストセッション履歴

---

### 4. 削除前確認

誤削除を防ぐため、削除時はバッチIDを入力する必要があります。

例:

```text
Batch 2 を削除する場合、確認欄に 2 と入力
```

---

## 追加/変更したDB

### 追加テーブル

```sql
import_batches
```

### wordsに追加した列

```sql
import_batch_id
```

既存の単語は `import_batch_id = NULL` です。
そのため、既存データが勝手に削除対象になることはありません。

---

## 追加URL

```text
/admin/import-batches
/admin/import-batches/<batch_id>
/admin/import-batches/<batch_id>/delete
```

---

## 反映

```powershell
git add .
git commit -m "add csv import batch management"
git push
```

## 使い方

1. masterでCSVインポートする
2. インポート結果に Batch ID が表示される
3. `/admin/import-batches` で履歴を見る
4. 削除したいBatchを開く
5. バッチIDを入力して削除
