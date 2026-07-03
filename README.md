# svtracker

Shadowverse: Worlds Beyond (Steam版) の対戦画面を監視し、

- 公式サイトのカード画像と画面上のカードを照合してプレイされたカードを判定
- ターン数・自分と相手の行動を記録
- 記録した対戦データから相手の次の行動を予測
- 現在の盤面・手札から最善に近い行動を提案

することを目指す個人利用向けツールです。

## できること / できないこと

- **できる**: カード画像同士の照合(pHash)、手札→盤面の差分によるプレイ検出、
  OCR/ピクセル色判定によるターン数・手番・PP・ライフ・エクストラPP・進化ポイント(EP)の読み取り、
  対戦ログのSQLite記録、記録に基づく簡易な相手行動予測、盤面状況からのリーサル検出・トレード提案・
  エクストラPPを含めたPP消費提案・進化ポイントを使うべきタイミングの提案。
  進化/超進化そのものも、進化ポイントが減ったフレームを検知してアクション履歴に記録します
  (誰が・何ターン目に進化したか。どのユニットに進化したかまでは特定しません、後述の制限を参照)。
  これらはシェル操作なしで完結するデスクトップGUI(Tkinter、`svtracker-gui`)からも操作できます。
- **精度に限界がある**: 盤面ユニットのATK/HPはカードマスタの基礎値をそのまま使っており、
  バフ/デバフ・疲労状態(攻撃済みかどうか)・進化による能力値上昇は画面から読み取っていないため、
  盤面表示は常に「攻撃可能・未進化」扱いです。進化イベント自体は進化ポイントの増減で検出できますが、
  盤面の複数ユニットの中でどれが進化したかまでは特定していません。より正確にするにはユニット上の
  ATK/HP表示OCRや、盤面枠ごとの進化演出(枠色の変化など)検出の追加実装が必要です。
- **できない/未検証**: 本開発環境はGUIもSteamクライアントも無いサンドボックスのため、
  実際のゲーム画面に対する認識精度・キャリブレーションはこの環境では検証できていません。
  実機(Windows + Steam版SVWB)でのキャリブレーションと調整が必須です。
  同様に公式サイト(shadowverse-wb.com)からのカード自動取得(`fetch-cards`)も、
  この開発環境からは対象サイトへのアクセスが行えなかったため実サイトに対しては未検証です。
  サイトのHTML構造が変わっている場合は `src/svtracker/cards/card_fetcher.py`
  冒頭のCSSセレクタ定数を実際のページに合わせて調整してください。
  うまく動かない場合は `import-cards` (後述)でローカルに用意した画像+CSVから
  カードDBを構築する方法を使ってください。
  GUIについては、ウィジェットの生成・操作・保存までの一連の流れをXvfb(仮想ディスプレイ)上で
  自動チェック済みですが、実際のWindowsデスクトップでの見た目・操作感は未確認です。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windowsは .venv\Scripts\activate
pip install -e ".[dev,windows,ocr]"
```

- `windows` extra: ウィンドウ自動検出 (`pygetwindow`)。Windows環境でのみ有効。
- `ocr` extra: ターン数/PP/ライフの文字をOCRで読み取るために**実質必須** (`pytesseract`)。
  別途 [Tesseract OCR本体](https://github.com/tesseract-ocr/tesseract) のインストールが必要です
  (Windowsはインストーラでパスを通すか `pytesseract.pytesseract.tesseract_cmd` を設定)。
  未導入の場合はターン/PP/ライフの自動読み取りが無効になり、ターン数は1のまま進みません。

## 使い方(GUI版・おすすめ)

Windowsインストーラを使う場合、コマンド操作は不要です。インストール後にデスクトップ/
スタートメニューの「svtracker」を起動すると、以下の4タブを持つウィンドウが開きます。

1. **カードDB タブ**: 「公式サイトから取得」または「ローカルの画像+CSVから取り込み」ボタンで
   カードマスタを用意します。
2. **キャリブレーション タブ**: 上部でキャプチャするモニタを選び、「スクリーンショットを撮る」
   ボタンで画面を取得します。右側の一覧から編集したい領域(手札・盤面・ターン表示など)を
   選んでから、画面プレビュー上をドラッグ(矩形)またはクリック(座標・手番判定用ピクセル)で
   指定します。手札・盤面のような複数枠の領域は、先頭2〜3枚だけドラッグして枚数を指定し
   「等間隔で自動補完」を押せば、間隔を推定して残りを自動生成できます(全部手でドラッグ
   する必要はありません)。手番判定の基準色も、プレビュー上をクリックするだけで登録できます。
   「regions.json / settings.json に保存」で確定します。
3. **監視 タブ**: 自分/相手のクラスを入力し「開始」。認識したプレイ・予測・提案が
   ログ欄にリアルタイム表示されます。「停止」で対戦記録が保存されます。
4. **統計 タブ**: 相手クラス名を入力すると、そのクラス相手に過去よく使われたカードの
   一覧が表示されます。

GUIも内部的には下記CLIと同じロジック(`svtracker.app.MonitorApp` など)を呼んでいるだけなので、
挙動や設定ファイルの場所は完全に共通です。

### コマンドラインが必要な場合

自動化やデバッグのために、GUIとは別に `svtracker`(CLI, コンソール表示あり)コマンドも
同梱されています。以下は主にそちらの説明です。

## 使い方(CLIコマンド版)

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

複数モニタ環境では、まずキャプチャ対象のモニタを確認してください。

```bash
svtracker list-monitors
```

ゲームを起動した状態で1枚キャプチャを保存し、手札・盤面の座標を調べます。

```bash
svtracker screenshot -o screenshot.png
# 特定のモニタを指定する場合:
svtracker screenshot -o screenshot.png --monitor 2
```

`--monitor` を省略した場合は `config/settings.json` の `monitor_index` が使われます。
GUI版では「キャリブレーション」タブ上部のモニタ選択欄で切り替えられ、選択は即座に
`config/settings.json` に保存されます。

`config/regions.example.json` を `config/regions.json` としてコピーし、
保存した画像を見ながら各カード枠の `[x, y, width, height]` を実際の座標に書き換えてください。
手札・盤面のような複数枠の領域を1枠ずつ手打ちするのは大変なので、GUI版の「等間隔で
自動補完」機能(先頭2〜3枚の座標から間隔を推定して残りを生成)を使うことをおすすめします。

ターン数・PP・ライフ・エクストラPP・進化ポイントの自動読み取りには `turn_indicator` /
`self_pp` / `self_life` / `opponent_life` / `self_extra_pp` / `self_ep` / `opponent_ep` の
各領域も実際の数字表示部分に合わせてください(OCRなので、余白を含めすぎず数字部分だけを
囲むと精度が上がります)。`self_extra_pp` はPP表示の近くにある持ち越し分(0〜2)、
`self_ep`/`opponent_ep` は残り進化ポイント表示です。進化ポイントが数字ではなく
アイコン(宝石など)で表示されるUIの場合はOCRでは読み取れないため、その場合は
これらの領域を未設定のままにしてください(進化検出・進化ポイント関連の提案のみ
無効になり、他の機能には影響しません)。

手番判定 (`active_player_pixel`) は数字OCRではなくピクセル色判定です。自分の手番の時と
相手の手番の時、それぞれのスクリーンショットで手番表示の色が変わるUIパーツ(背景色や
ハイライトなど)を1点選び、その座標を `active_player_pixel` に、実際の色(RGB)を
`config/settings.json` の `self_turn_color` / `opponent_turn_color` に設定してください。
`config/settings.example.json` の値はダミーなので必ず実際の色に置き換える必要があります。

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
  モニタ番号、マッチング閾値、手番判定用の基準色 (`self_turn_color` / `opponent_turn_color`) など。
- `config/regions.json` (`config/regions.example.json` をコピーして作成): 手札・盤面などの
  画面上の矩形領域と、手番判定用の座標 (`active_player_pixel`)。
  **解像度・UIレイアウトごとに調整が必須**です。

## Windowsインストーラ

Python環境を用意しなくても使えるように、PyInstallerでの単体exe化(GUI版・CLI版の両方)と
Inno Setupでのインストーラ作成に対応しています。実際のビルドはGitHub Actions
(`windows-latest`ランナー)で行われるため、この開発環境(Linuxサンドボックス)では
作れませんが、CIで実機Windows相当の環境を使ってビルド・GUI起動・動作確認しています。

- 入手方法: GitHubリポジトリの Actions タブ → `Build Windows Installer` ワークフロー
  → 対象の実行 → Artifacts から `svtracker-windows-installer` (インストーラ) または
  `svtracker-exe` (GUI版 `svtracker-gui.exe` とCLI版 `svtracker.exe` の単体exe2つ) を
  ダウンロード。タグ `v*` をpushすると自動でも走ります。
- インストーラは `svtracker-gui.exe`(GUI・デスクトップ/スタートメニューのメインアイコン)、
  `svtracker.exe`(CLI・上級者向けの別ショートカット)、`config/*.example.json`、READMEを
  `Program Files\svtracker` 配下に配置します。`data/`, `config/settings.json`,
  `config/regions.json` はGUIの「キャリブレーション」タブから作成・保存できます。
- **OCR(ターン/PP/ライフ読み取り)を使うには、インストーラとは別に
  [Tesseract OCR本体](https://github.com/tesseract-ocr/tesseract) のインストールが必要です**
  (バイナリはライセンス・サイズの都合でインストーラに同梱していません)。
- ローカルでビルドする場合は `packaging/entrypoint.py`(CLI)・
  `packaging/gui_entrypoint.py`(GUI)をそれぞれ PyInstaller で、
  `packaging/installer.iss` を Inno Setup (`ISCC.exe`) でビルドしてください。
  具体的なコマンドは `.github/workflows/build-windows-installer.yml` を参照してください。

## 仕組みの概要

```
画面キャプチャ(mss)
   -> 領域切り出し(config/regions.json)
   -> ターン数/手番/PP/ライフ/エクストラPP/進化ポイントを読み取り
      (capture/ocr_reader.py: OCR + ピクセル色判定)
   -> カード照合(pHashで公式カード画像DBと比較, cards/card_matcher.py)
   -> 手札/盤面の差分からプレイ検出、進化ポイントの減少から進化/超進化を検出
      (game/event_detector.py)
   -> 対戦状態を記録(game/match_tracker.py) + SQLiteに永続化(storage/match_log.py)
   -> 相手の次の一手を予測(prediction/predictor.py: 履歴頻度 + 新規性 + PPカーブ適合度)
   -> 自分の最善に近い行動を提案
      (prediction/advisor.py: リーサル判定/トレード判定/エクストラPPを含むPP消費最適化/進化ポイント活用提案)
```

予測・アドバイスは厳密なゲームAI/探索ではなく、説明可能なヒューリスティックです。
対戦記録が蓄積されるほど「相手の次の行動予測」の精度は上がっていきます
(初回や対戦記録が無いクラス相手では、カーブ適合度と新規性のみで予測します)。

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
