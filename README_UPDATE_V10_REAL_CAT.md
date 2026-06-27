# English Pocket Real Cat Design v10

## 変更内容

さっき決めたリアル寄り猫デザインシートを、アプリ用の猫素材として導入しました。

差し替えた画像:
- cat-neutral.png  : 通常（立つ）
- cat-play.png     : 正解 / 高得点（遊ぶ）
- cat-study.png    : クイズ中（座る）
- cat-sad.png      : 不正解 / 低得点（しょんぼり）
- cat-rest.png     : 10問普通（リラックス）
- cat-sleepy.png   : おやすみ（寝る）

## ポイント

- 犬ではなく猫ベースに戻しています
- さっきのデザインシートから切り出しています
- 背景は透明化しています
- DB変更はありません
- ユーザー、単語、学習履歴は消えません
- コード変更はほぼなく、画像差し替え中心です

## Render反映

```powershell
git add .
git commit -m "update real cat design assets"
git push
```

Renderの自動デプロイがONなら自動反映されます。
手動なら Render → Manual Deploy → Deploy latest commit を押してください。
