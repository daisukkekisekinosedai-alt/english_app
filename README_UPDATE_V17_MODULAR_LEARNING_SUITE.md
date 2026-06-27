# にゃんにゃんイングリッシュ v17 Modular Learning Suite

## 方針

見た目系の失敗を踏まえ、今回は **機能的な大型アップデート** に振り切りました。

重要ポイント:

- 猫の部屋 / 家具 / 着せ替えは廃止済み
- 学習効果を上げる機能だけ追加
- 機能ごとに番号を付与
- 後から「1,4,5だけ使う」「2,3は使わない」のように選べる

---

## 機能番号

### 1. スマート学習エンジン

URL: `/smart`

学習履歴をもとに、今日やるべき単語を自動選定します。

できること:

- 復習すべき単語を自動判定
- 何度も間違えた単語を優先
- 正答率が低い単語を優先
- 7日以上触れていない単語を忘却防止として抽出
- 新規単語も混ぜる
- おすすめ10問を作成

おすすめ10問:

```text
/session/start?mode=choice&scope=smart&count=10
```

---

### 2. 集中モード

URL: `/focus`

25分集中の学習導線です。

できること:

- 25分タイマー
- 3分準備
- 12分おすすめ10問
- 7分ミス回収
- 3分仕上げ

---

### 3. 今日の学習計画

URL: `/plan`

今日の学習フェーズとロードマップを自動で出します。

できること:

- 診断フェーズ
- 弱点補強フェーズ
- 習慣化フェーズ
- 得点力強化フェーズ
- 今日 / 明日 / 今週のやること表示

---

### 4. 試験モード

URL: `/exam`

本番寄りのドリルを作ります。

できること:

- スマート20問
- スマート30問
- リスニング20問
- 現在の readiness 判定
- 試験後にミスノートへつなぐ導線

---

### 5. ミスノート

URL: `/mistakes`

間違えた単語だけを集約します。

できること:

- ミス単語一覧
- ミス回数
- 最後に間違えた日
- 過去の誤答
- 例文
- 最優先 / 近日ミス / 復習候補 の分類

---

## 機能の有効化 / 無効化

環境変数 `ENABLED_FEATURES` で使う機能を選べます。

### 全部使う

未設定でOKです。

```text
ENABLED_FEATURES=
```

または

```text
ENABLED_FEATURES=1,2,3,4,5
```

### 1,4,5だけ使う

```text
ENABLED_FEATURES=1,4,5
```

この場合:

- 1. スマート学習エンジン
- 4. 試験モード
- 5. ミスノート

だけが有効になります。

### 2,3を外したい場合

```text
ENABLED_FEATURES=1,4,5
```

---

## 追加/変更した主なファイル

- `app.py`
- `templates/smart.html`
- `templates/focus.html`
- `templates/plan.html`
- `templates/exam.html`
- `templates/mistakes.html`
- `templates/features.html`
- `templates/base.html`
- `templates/index.html`
- `static/css/style.css`

---

## DB変更

なし。

既存のユーザー、単語、学習履歴は消えません。

---

## Render反映

```powershell
git add .
git commit -m "add modular learning suite"
git push
```

Renderの自動デプロイがONならそのまま反映されます。

---

## Renderで機能を絞る場合

Renderの Environment Variables に追加:

```text
ENABLED_FEATURES=1,4,5
```

その後、再デプロイしてください。
