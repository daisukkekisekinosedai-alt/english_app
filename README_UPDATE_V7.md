# にゃんにゃんイングリッシュ Update v7

## 変更内容

### 猫の部屋を追加

新しい画面 `/cat-room` を追加しました。

学習実績に応じて、猫の部屋に家具や飾りが増えます。

## 解放アイテム

- ふわふわクッション: 10問回答
- 毛糸ボール: 3日連続学習
- 満点の王冠: 10問満点1回
- キャットタワー: 100問回答
- 英単語の本棚: Lv10
- 努力のトロフィー: 500問回答
- お気に入りフィッシュ: お気に入り5語
- 正答率リボン: 30問以上回答かつ正答率80%以上
- 連続学習の窓: 7日連続学習
- 語彙の観葉植物: 100問正解

## DB変更

なし。

既存の `study_logs`, `test_sessions`, `user_word_flags` などから自動判定します。

## Render反映

```powershell
git add .
git commit -m "add cat room"
git push
```

Renderの自動デプロイがONなら自動反映されます。
手動なら Render → Manual Deploy → Deploy latest commit を押してください。
