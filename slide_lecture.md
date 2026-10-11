# `slide_lecture.py` の使い方と内部構造

> 対象：2026年10月11日に提供された `slide_lecture.py` の構成．WebUIからも呼び出されるCLIバックエンドです．

## 1．概要

PDF形式の講義・研究発表資料から，ナレーション原稿，対訳字幕，ポインタ位置，音声，動画を段階的に生成します．講義／研究発表，主言語の日本語／英語，対象ページ，ポインタ決定方式を設定できます．

```text
PDF → pages/*.png → explanations/*.txt
                         ↓
                explanations/*_align.json
                         ↓
                   audio/*.mp3
                         ↓
                   video/*.mp4
                         ↓
              完成MP4と日英SRT
```

## 2．CLIの基本操作

```bash
# PDFをPNGに変換（デフォルト動作）
python3 slide_lecture.py presentation.pdf

# ナレーション原稿の生成
python3 slide_lecture.py presentation.pdf --from explain

# アライメント・翻訳
python3 slide_lecture.py presentation.pdf --from align

# TTS
python3 slide_lecture.py presentation.pdf --from tts

# 動画生成と結合
python3 slide_lecture.py presentation.pdf --from video
```

**注意：** `--from` は名称から「指定工程以降のみを実行」と誤解しやすいですが，このプログラムは依存する前段の生成処理も必要に応じて呼びます．既存の生成物は原則として再利用されます．指定工程で実行を終了するため，段階ごとに内容を確認できます．

### 主要オプション

| オプション | 用途 |
|---|---|
| `--config PATH` | `config.yaml` 以外の設定を使用 |
| `--from pdf\|explain\|align\|tts\|video` | 終了する生成ステージを指定 |
| `--force` | 指定ステージに応じて既存の生成物を削除し，再生成 |
| `--output DIR` | 出力先プロジェクトディレクトリ |
| `--mode lecture\|research` | 講義／研究発表のプロンプト |
| `--lang ja\|en` | 音声の主言語 |
| `--pages 1-5,8` | 対象ページ |
| `--skip-pages 2,4` | 除外ページ |
| `--visual-mode vlm\|pdf` | VLM併用／PDF構造ベースのポインタ解析 |

例：

```bash
python3 slide_lecture.py presentation.pdf \
  --mode lecture --lang ja --from align \
  --pages 1-20 --skip-pages 5,9-10 --visual-mode vlm
```

引数を省略した場合は，まずプロジェクトの `project.json` を確認し，次に `config.yaml` の設定値を利用するものがあります．

## 3．生成物の配置

`presentation.pdf` のデフォルト出力先は `presentation_lecture/` です．

```text
presentation_lecture/
├── project.json                 # モード・ページ・個別指示など
├── pages/
│   ├── 001.png
│   └── ...
├── explanations/
│   ├── _course_overview.txt
│   ├── 001.txt
│   ├── 001_align.json
│   └── ...
├── audio/
│   ├── 001.mp3
│   └── ...
├── video/
│   ├── 001.mp4
│   └── ...
├── presentation.mp4
├── presentation_ja.srt
└── presentation_en.srt
```

ページ番号はPDFのページ番号（1始まり）です．対象ページを絞った場合も元PDFのページ番号を維持します．

## 4．原稿生成の仕組み

`extract_page_text()` がPDF内のテキストを抽出します．`build_course_overview()` は全体の流れを要約し，`make_explanation()` が各ページの画像と前後のページ情報を使って原稿を生成します．

プロンプトには次を組み合わせます．

- `get_narration_prompt()` が返す講義／研究発表・日本語／英語別の**共通システムプロンプト**
- 講義・発表全体の概要，現在のページ，前後ページの本文と前ページの原稿
- 現在のスライド画像
- **該当ページに保存された追加プロンプト**（設定がある場合のみ）

`make_explanation()` の `additional_prompt` は，ユーザメッセージ末尾にそのページ固有の指示を付けます．既存の共通システムプロンプトは変更しません．

### スライド別追加プロンプト

出力先プロジェクトの `project.json` に保存します．

```json
{
  "slide_prompts": {
    "3": "図を左から右へ説明してください．",
    "12": "待機チャネルがアドレスであることを強調してください．"
  }
}
```

`get_slide_additional_prompt()` がページ番号の文字列キーを使って取得します．`generate_explanations()` と `generate_single_explanation()` のどちらもこの関数を使用します．

CLIで設定ファイルを手動編集する場合は，**既存の `project.json` の他の項目を消さず**，`slide_prompts` を追記してください．すでに生成済みの原稿には指示が遡及しません．そのページを再生成する必要があります．CLIの一括 `--force` は広範囲の生成物を削除することがあるため，特定ページだけならWebUIの個別再生成が安全です．

## 5．字幕・ポインタ位置の生成

`generate_single_alignment()` / `generate_alignments()` が，ナレーションの各文に対して表示するスライド要素を決定し，日英字幕用の対訳も生成します．

- `extract_page_blocks()`：PDFテキスト，コード行，画像領域の抽出
- `run_vlm_element_detection()`：VLMが返した要素情報の解釈とbbox変換
- `parse_vlm_bounding_box()`：0～1000の正規化座標から画像上の座標へ変換
- `align_narration_with_blocks()`：各ナレーション文とブロックIDを対応付け
- `translate_sentences()`：主言語から他言語への字幕翻訳
- `build_pointer_schedule()`：レーザーポインタの位置・時刻列を組み立て

`--visual-mode vlm` はVLMによる図内要素の抽出を併用します．`pdf` は主にPDF構造を利用します．`project.json` の `slide_visual_modes` にページ別の方式が記録されていれば，その設定も参照されます．検出した要素が常に正しいとは限らないため，詳細編集画面で確認してください．

## 6．日本語ヨミ変換・TTS

`generate_single_tts()` / `generate_tts()` と `_run_tts_stage()` が音声生成を担います．主言語のTTS設定（`config.yaml` の `tts.ja` または `tts.en`）を選択します．

日本語TTSでは `tts_filter.yaml` と `tts_filter.py` を使うヨミ変換の経路があります．この変換は**読み上げ用テキスト**に適用され，原稿・字幕の表示文字列を一律にカタカナへ置き換える目的ではありません．

## 7．動画・字幕・チャプター

`generate_single_page_video()` / `generate_page_video()` がページごとの動画をFFmpegで作成します．`create_full_srt()` は字幕を出力します．`create_chapter_metadata()` はチャプター情報を組み立て，`concat_videos()` はページ動画を結合して最終MP4を作成します．

FFmpegは `check_ffmpeg()` で確認し，`detect_best_video_encoder()` が利用可能なエンコーダを検出します．使用可能なハードウェアエンコーダがない場合は `libx264` にフォールバックします．

## 8．差分実行と `--force`

既存の画像，原稿，アライメント，音声，動画は，処理内容と `--force` の指定に応じて再利用されます．`_force_cleanup()` は `--force` の指定ステージに基づいて下流の生成物を削除します．

**原稿だけ直した場合の注意：** ファイルを書き換えただけでは，古いアライメント・音声・動画が残ることがあります．再生成する範囲を意識して作業してください．WebUIは各操作に応じた下流成果物の無効化機能を持っています．

## 9．主な関数を読む順序

1. `main()`：引数，設定，ステージの分岐
2. `pdf_to_images()`，`extract_page_text()`：PDF入力
3. `build_course_overview()`，`generate_explanations()`，`make_explanation()`：原稿
4. `generate_alignments()` と関連するVLM・bbox・翻訳処理：字幕とポインタ
5. `_run_tts_stage()`：音声
6. `_run_video_stage()`，`concat_videos()`：動画と完成物

## 10．トラブルシューティング

- **原稿に追加指示が反映されない**：`project.json` の保存先とページ番号を確認し，既存原稿の再利用でないことを確認します．
- **VLM要素が得られない**：モデルのJSON形式とbbox座標を確認します．解析不能な要素は採用されないことがあります．
- **音声が読みにくい**：`tts_filter.yaml` の辞書，ヨミ変換の設定，TTS接続先を確認します．
- **動画生成に失敗する**：FFmpegのインストール，ハードウェアエンコーダの利用可否，音声・アライメントの有無を確認します．
