# svtracker

Shadowverse: Worlds Beyond (Steam版) の対戦画面を監視し、

- 公式サイトのカード画像と画面上のカードを照合してプレイされたカードを判定
- ターン数・自分と相手の行動を記録
- 記録した対戦データから相手の次の行動を予測
- 現在の盤面・手札から最善に近い行動を提案

することを目指す個人利用向けツールです。

## できること / できないこと

- **できる**: カード画像同士の照合(pHash)、対戦ログのSQLite記録、記録に基づく
  簡易な相手行動予測、盤面状況からのリーサル検出・トレード提案・PP消費提案。
- **できない/未検証**: 本開発環境はGUIもSteamクライアントも無いサンドボックスのため、
  実際のゲーム画面に対する認識精度・キャリブレーションはこの環境では検証できていません。
  実機(Windows + Steam版SVWB)でのキャリブレーションと調整が必須です。
  同様に公式サイト(shadowverse-wb.com)からのカード自動取得(`fetch-cards`)も、
  この開発環境からは対象サイトへのアクセスが行えなかったため実サイトに対しては未検証です。
  サイトのHTML構造が変わっている場合は `src/svtracker/cards/card_fetcher.py`
  冒頭のCSSセレクタ定数を実際のページに合わせて調整してください。
  うまく動かない場合は `import-cards` (後述)でローカルに用意した画像+CSVから
  カードDBを構築する方法を使ってください。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windowsは .venv\Scripts\activate
pip install -e ".[dev,windows,ocr]"
```

- `windows` extra: ウィンドウ自動検出 (`pygetwindow`)。Windows環境でのみ有効。
- `ocr` extra: ターン数/PPなどの文字をOCRで読み取りたい場合 (`pytesseract`)。
  別途 [Tesseract OCR本体](https://github.com/tesseract-ocr/tesseract) のインストールが必要です。

## 使い方

### 1. カードマスタDBを用意する

公式サイトから自動取得を試す場合:

```bash
svtracker fetch-cards
```

うまく取得できない場合は、手元に用意した画像+CSVから取り込みます:

```bash
svtracker import-cards ./my_card_images ./my_card_metadata.csv
```

CSVフォーマット (`data/cards/` 配下の画像を想定):

```csv
card_id,name,clan,cost,card_type,rarity,filename,base_atk,base_hp
10112210,ロビンフッド,エルフ,4,フォロワー,レジェンド,10112210.png,3,3
```

### 2. 画面領域をキャリブレーションする

ゲームを起動した状態で1枚キャプチャを保存し、手札・盤面の座標を調べます。

```bash
svtracker screenshot -o screenshot.png
```

`config/regions.example.json` を `config/regions.json` としてコピーし、
保存した画像を見ながら各カード枠の `[x, y, width, height]` を実際の座標に書き換えてください。

### 3. 監視を開始する

```bash
svtracker run --self-clan エルフ --opponent-clan ロイヤル
```

一定間隔(既定1秒、`config/settings.json`の`capture_interval_sec`で変更可)で画面をキャプチャし、
検出したプレイを標準出力にログしながら、相手の次の行動予測と自分への行動提案を表示します。
`Ctrl+C` で終了すると対戦記録がDBに保存されます。

### 4. 蓄積した対戦統計を見る

```bash
svtracker stats ロイヤル
```

## 設定ファイル

- `config/settings.json` (`config/settings.example.json` をコピーして作成): キャプチャ間隔、
  モニタ番号、マッチング閾値など。
- `config/regions.json` (`config/regions.example.json` をコピーして作成): 手札・盤面などの
  画面上の矩形領域。**解像度・UIレイアウトごとに調整が必須**です。

## 仕組みの概要

```
画面キャプチャ(mss)
   -> 領域切り出し(config/regions.json)
   -> カード照合(pHashで公式カード画像DBと比較, cards/card_matcher.py)
   -> 手札/盤面の差分からプレイ検出(game/event_detector.py)
   -> 対戦状態を記録(game/match_tracker.py) + SQLiteに永続化(storage/match_log.py)
   -> 相手の次の一手を予測(prediction/predictor.py: 履歴頻度 + 新規性 + PPカーブ適合度)
   -> 自分の最善に近い行動を提案(prediction/advisor.py: リーサル判定/トレード判定/PP消費最適化)
```

予測・アドバイスは厳密なゲームAI/探索ではなく、説明可能なヒューリスティックです。
対戦記録が蓄積されるほど「相手の次の行動予測」の精度は上がっていきます
(初回や対戦記録が無いクラン相手では、カーブ適合度と新規性のみで予測します)。

## テスト

画面キャプチャ・公式サイト通信を含まない部分(カード照合・対戦記録・予測・アドバイス)は
オフラインでテストできます。

```bash
pip install -e ".[dev]"
pytest
```

## 注意事項

- 本ツールは画面をキャプチャして解析するだけで、ゲームクライアントへの
  自動操作・メモリ改ざん・通信の書き換えなどは一切行いません。
- 公式サイトのカード画像を取得・保存する機能を含みます。利用は個人の学習・観戦補助目的の
  範囲にとどめ、Cygames社の利用規約を確認の上で自己責任で使用してください。
- 対戦相手の情報を記録する機能はローカルのSQLiteファイルに保存するのみで、
  外部送信は行いません。
