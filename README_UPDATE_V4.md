# English Pocket Update v4

## 変更内容

### masterアカウント固定化

masterアカウントは固定で自動作成されます。

```text
ユーザー名: master
パスワード: giants
```

最初に登録したユーザーをmasterにする方式は廃止しました。

既存DBがある場合も、起動時に以下を実行します。

- username が `master` のユーザーをmaster化
- masterが存在しなければ自動作成
- masterのパスワードを `giants` に更新
- master以外のユーザーは通常ユーザー化

Renderでは環境変数で変更もできます。

```text
MASTER_USERNAME=master
MASTER_PASSWORD=giants
```

### 単語一括削除

master専用で `/admin/words` を追加しました。

できること:

- すべての単語を削除
- カテゴリ単位で削除
- 最近追加された単語から選択削除

削除対象:

- words
- study_logs
- user_word_flags

つまり、削除した単語に紐づく学習履歴・お気に入りも削除されます。

## Render反映

zipの中身をGitHubのリポジトリに上書きしてから以下を実行してください。

```powershell
git add .
git commit -m "update fixed master and bulk delete"
git push
```

Renderの自動デプロイがONなら自動反映されます。
手動なら Render → Manual Deploy → Deploy latest commit を押してください。
