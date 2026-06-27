# English Pocket Update v8

## 変更内容

### 猫の種類を追加

プロフィール画面で選べる相棒ねこを増やしました。

追加した猫:

- ちゃとらねこ
- くろねこ
- しろねこ
- グレーねこ
- みけねこ
- タキシードねこ
- シャムねこ
- ぶちねこ

## リアクション対応

追加した猫も以下の状態に対応しています。

- ホーム
- 通常
- クイズ
- リスニング
- 正解
- 不正解
- 10問高得点
- 10問通常
- 10問低得点

## DB変更

なし。

既存ユーザーは今まで選んでいた猫のままです。
プロフィール画面から新しい猫に変更できます。

## Render反映

```powershell
git add .
git commit -m "add more cat types"
git push
```

Renderの自動デプロイがONなら自動反映されます。
手動なら Render → Manual Deploy → Deploy latest commit を押してください。
