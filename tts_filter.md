# `tts_filter.py` ヨミ変換フィルタ解説

> 対象：第7段階リファクタリング後の `tts_filter.py`．現行のプロンプトと辞書定義はコード・YAMLを正本とし，ここでは処理と設定方法を説明します．

## 1．目的

`tts_filter.py` は，日本語TTSに渡す技術用語・英語表記・識別子・コマンドなどを，LLMによって音声向けの読みへ変換する前処理プログラムです．**原文の意味や説明内容を改変することが目的ではありません**．

たとえば `Linux`，`cnt`，`/usr/bin` など，文脈に依存して読み方が変わる文字列を対象とします．漢字・数字・単位などは必要以上に変換しない方針です．

## 2．処理の流れ

```text
入力文章（ファイルまたは標準入力）
           │
           ▼
   段落ごとに分割
           │
           ▼
  基本プロンプト＋YAML辞書
           │
           ▼
  OpenAI互換Chat Completion API
           │
           ▼
  変換結果を結合し出力
```

使用するサーバは `tts_filter.yaml` の `server` で指定します．外部APIだけでなくローカルのOpenAI互換LLMサーバも利用できます．

## 3．主な関数

| 関数 | 役割 |
|---|---|
| `load_config()` | `tts_filter.yaml` を読み込む |
| `build_dictionary_text()` | 辞書項目をLLMが理解できる文字列に変換する |
| `build_system_prompt()` | 基本変換ルールに辞書を組み込む |
| `make_client()` | OpenAI互換APIクライアントを構築する |
| `split_paragraphs()` | 入力を空行単位の段落へ分割する |
| `transform()` | 1つの対象文章をLLMで変換する |
| `transform_text()` | 文章全体を段落ごとに変換する |
| `main()` | CLI引数の解析と入出力 |

辞書展開には `{{DICTIONARY}}` プレースホルダーと，`DEFAULT_SYSTEM_PROMPT_TEMPLATE` を利用します．実際にプロンプトや辞書の形式を変更するときは，実行環境の `tts_filter.py` と `tts_filter.yaml` を合わせて確認してください．

## 4．設定ファイル例

以下は設定構造の例です．接続先とモデル名は各環境に合わせて変更してください．

```yaml
server:
  base_url: http://localhost:11434/v1
  api_key: dummy
  model: your-model

generation:
  temperature: 0

dictionary:
  Linux: リナックス
  cnt: カウンタ
  ls: エルエス
```

辞書はLLMに読み方の参考情報を与えるものです．厳密な文字列置換を保証するものではなく，変換結果はモデルによって変わる可能性があります．

## 5．CLI使用方法

```bash
# ファイルから読み，ファイルへ書く
python3 tts_filter.py -i input.txt -o output.txt

# 標準入力から変換
printf 'Linux で cnt を確認します．\n' | python3 tts_filter.py

# 設定ファイルを切り替える
python3 tts_filter.py -c custom_tts_filter.yaml -i input.txt
```

公開ドキュメントで案内されているオプションは `-c/--config`，`-i/--input`，`-o/--output` です．

## 6．WebUIと動画生成との関係

`slide_lecture.py` は日本語TTS処理の前に必要に応じて `apply_tts_filter()` を実行します．`app.py` の管理者向け「設定」画面には，`_build_dict_editor()` によるヨミ辞書の編集・テスト画面があります．

ヨミ変換は **TTSに入力するための音声用テキスト** に対する前処理です．スライドに表示するナレーションや字幕の文字列を自動的に書き換えるものではありません．

スライドの追加プロンプトは `project.json` の `slide_prompts` に保存される**ナレーション生成の指示**であり，`tts_filter.yaml` に保存する**ヨミ辞書**とは目的が異なります．

## 7．テストと注意点

- 同じ用語でも文脈により適切な読みが異なるため，変更後は実際のナレーション文章を使って試してください．
- `#` や演算子・パス・コマンドオプションなどは，意図しない読みへ変換されることがあります．
- 辞書を変更しただけでは生成済みMP3の音声は変わりません．必要なページのTTSを再生成してください．
- プライベートな資料を扱う場合，LLM/TTSのAPI接続先とデータの扱いを確認してください．

詳細なプロンプト実装を改変する場合は，`tts_filter.py` の現在の定数・関数定義を必ず確認し，既存の変換ルールを不用意に簡略化しないでください．
