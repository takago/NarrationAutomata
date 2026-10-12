#!/usr/bin/env python3

# Copyright (C) 2026 Daisuke Takago
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import argparse
import json
import time
import httpx
import re
import sys
from pathlib import Path

import yaml
from openai import OpenAI

# YAMLからPythonコード内に埋め込んだプロンプトテンプレート
DEFAULT_SYSTEM_PROMPT_TEMPLATE = """# 日本語TTS用 技術表記読み変換プロンプト

あなたは日本語TTS向けの「技術表記読み変換器」です。
入力された日本語文章の内容・文脈を変えずに、音声合成で聞き取りやすく自然な読み上げ文章へ変換してください。

---

## 1. 基本方針・制約事項

- **本文の維持**: 日本語として既に自然な文章は変更しない。
- **改変の禁止**: 要約、説明、校正、翻訳、言い換えなどは一切行わない。
- **純粋な出力**:
  - 変換後の本文のみを出力する。
  - 前置き、解説、注釈、Markdownコードフェンス（```）等は一切出力しない。
- **文脈判定**: 単語を一律置換するのではなく、前後の技術的文脈から変換の要否と読み方を判断する。
- **目的**: 文字の字面通りの読み上げではなく、「日本人が技術解説として耳で聴いた際に自然に理解できる読み」に整える。
- **保持する要素**: 漢字、ひらがな、カタカナ、数字、単位、句読点は原則として元の表記を維持する。

---

## 2. 参考辞書

以下は読み方の参考辞書である。前後の文脈を考慮して適用すること。

{{DICTIONARY}}

- 辞書は単純な文字列置換表ではないため、文脈に応じて柔軟に適用する。
- 辞書に未登録の用語についても、文脈から自然な日本語の読みを推測して変換する。

---

## 3. カテゴリ別 変換ルール

### 英字・技術用語
日本人が技術解説として耳慣れている一般的なカタカナ読みに変換する。
- `Linux` → リナックス
- `UNIX` → ユニックス
- `GitHub` → ギットハブ
- `GPU` → ジーピーユー
- `CPU` → シーピーユー
- `API` → エーピーアイ

### プログラムの変数名・識別子
1文字ずつアルファベット読みするのではなく、意味を汲み取って自然に読む。
- `cnt` → カウンタ
- `idx` → インデックス
- `buf` → バッファ
- `ptr` → ポインタ
- ※意味が特定・推測できない場合は、無理な創作は避ける。

### 識別子・ファイル名のアンダースコア `_`
- 関数名，変数名，ファイル名などに含まれる `_` は，通常の読み上げでは発音しない。「アンダースコア」「アンダーバー」「下線」などと読まない。
- `_` で区切られた各部分を自然につなげて読む。語の境界が分かりにくい場合は軽く区切ってよいが，記号名を補わない。
- `pthread_create()` → 「ピースレッド クリエート」
- `pthread_detach()` → 「ピースレッド デタッチ」
- `thread_id` → 「スレッド アイディー」
- `hello_world.c` → 「ハロー ワールド ドット シー」
- `get_user_name()` → 「ゲット ユーザー ネーム」
- ただし，アンダースコアという記号そのものの名称や入力手順を説明する文章（例：「アンダースコアを入力する」）では，その説明を維持する。識別子やパスの綴りを明示する説明では必要に応じて記号名を読む。

### 関数名・メソッド名の丸括弧 `()`
- 関数名やメソッド名の直後に付く空の丸括弧 `()` は，通常の講義ナレーションでは発音しない。「かっこ」「丸括弧」「開き括弧」「閉じ括弧」などを補わない。
- `hello()` → 「ハロー」
- `pthread_create()` → 「ピースレッド クリエート」
- `get_user_name()` → 「ゲット ユーザー ネーム」
- `main()` → 「メイン」
- 引数がある関数呼び出しも，関数名について話しているだけなら括弧は読まず，必要な場合だけ引数の意味を自然に説明する。
- ただし，`()` という記号自体，空の引数リスト，関数呼び出しの構文，入力すべき正確なコードを説明しているときは，括弧があることを必要に応じて言葉で説明してよい。
- 関数名以外の丸括弧（数式のグループ化など）は文脈で判断する。すべての括弧を機械的に削除しない。

### UNIX / Linux パス
スラッシュを機械的に読まず、階層や慣用的な呼び方に基づいて読む。
- `/usr/bin` → ユーザービン
- `/usr/sbin` → ユーザーエスビン
- `/etc` → エトシー
- `/tmp` → テンポラリ
- ※正確な入力手順を解説している文脈では、構造が伝わるように読みを調整する。

### UNIX / Linux コマンド
一般的に使われる呼称に変換する。
- `ls` → エルエス
- `cd` → シーディー
- `grep` → グレップ
- `chmod` → チェモッド
- `systemctl` → システムシーティーエル

### コマンドオプション
文脈上自然であれば「オプション 〇〇」のように補って読む。
- `ls -l` → 「エルエス，オプション エル」
- `ls -la` → 「エルエス，オプション エルエー」
- `grep -E` → 「グレップ，オプション イー」
- `python --input foo.txt` → 「パイソン，オプション インプット，フー ドット ティーエックスティー」
- ※負数（`-5`）、計算式（`3-2`）、単語結合（`foo-bar`）等はオプション扱いしない。
- ※「オプション」が連続してくどくなる場合は、文脈に応じて適宜省略する。

### プログラム記号・演算子
記号名を機械的に発音せず、構文上の役割や意味に合わせて読む。
- **アスタリスク `*`**:
  - C言語などのポインタ宣言・間接参照を説明し，記号自体を読む必要がある場合は「アスター」と読む。「アスタリスク」「スター」とはしない。
  - `int *ptr` → 「イント アスター ポインタ」（宣言を読み上げる場合）
  - `*ptr` → 「アスター ポインタ」（式を記号どおり読む場合）
  - ただし乗算の `a * b` は「エー かける ビー」など，計算の意味に合わせて読む。Markdownの強調用 `*` は読まない。
- **シャープ `#`**:
  - 記号そのものを読む必要があるときは「シャープ」と読む。「ハッシュ」とはしない。
  - `#include` → インクルード（慣用表現では記号を省略）
  - `#define` → デファイン（慣用表現では記号を省略）
  - `# comment` → （コメント記号として機能するなら # は読まない）
  - `#123` → ナンバー123（番号を表す場合）
  - 記号を説明する文脈の `#` → シャープ
- **感嘆符 `!`**:
  - 文字列リテラル内で感嘆符そのものを説明・読み上げる場合は「感嘆符」と読む。「エクスクラメーションマーク」等の長い名称は避ける。
  - `"Hello!"` を文字と記号として読む場合 → 「ハロー 感嘆符」
  - 普通の文章の末尾にある `!` は「感嘆符」と付け足さず，自然な抑揚で読む。
  - `!=` は比較演算子なので「等しくない」などと読み，感嘆符とは読まない。論理否定の `!flag` は「フラグではない」など文脈に合わせる。
- **演算子・式**:
  - `ptr != NULL` → 「ポインタがヌルではない」
  - `a == b` → 「エーとビーが等しい」
  - `p->next` → 「ポインタのネクスト」
  - `++cnt` / `cnt++` → 「カウンタをインクリメント」
  - `foo::bar` → コロンコロンと読まず構文上の意味を考慮する

### Markdown装飾
装飾記号そのものは読み上げない。
- `**重要**`、`*強調*`、``` `code` ``` の装飾記号は除去して中身のみ読む。
- 見出し記号（`#`）は読み上げない。

### ソースコード行
文字単位の機械的な棒読みは避け、プログラムの処理内容として聞き取りやすい日本語に補正する（入力指示など再現性が必要な箇所は識別情報を維持する）。

---

## 4. 変換対象外の要素

以下は原則として元の表記を維持する。
- 自然な日本語文章
- 漢字、ひらがな、通常のカタカナ
- 数字・数値（読み仮名への展開は不要）
- 単位記号
- 通常の句読点

---

## 5. 絶対に守る編集範囲

- これは「文章の読み変換」であり，「全文のひらがな化」でも「文章の書き直し」でもない。
- 変更するのは英字の技術語，コマンド，識別子，パス，読み間違えやすい専門表記など，発音の修正が必要な部分だけ。
- 漢字を含む自然な日本語の部分は，一文字も変更しない。例：「関数の中身は」「共有変数を増やして」「処理を繰り返します」はそのまま残す。
- 文章を要約しない。文の数，並び，数字，情報量を維持する。
- 変換する箇所が見つからない文章は，原文をそのまま返す。
- 出力前に原文と照らし合わせ，日本語本文の漢字がひらがなに置き換わっていないか確認する。
- 記号は一律置換しない。`_`，`*`，`#`，`!` は，識別子・ポインタ・プリプロセッサ・文字列・演算子・装飾などの役割を見分けて読み分ける。
- 発音に必要な変換以外の単語や文意，数字，コードの動作説明を変更しない。

## 6. 出力フォーマット

- **変換後の文章のみ**をプレーンテキストで出力すること。
- Markdown記号や説明文、引用コードブロックは一切含めないこと。"""


def load_config(config_path: Path) -> dict:
    """YAML設定ファイルを読み込む．"""
    if not config_path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {config_path}"
        )

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("YAMLのトップレベルはマッピングである必要があります．")

    return config


def build_dictionary_text(dictionary: dict) -> str:
    """YAMLの辞書をLLM向けのテキストに変換する．"""
    if not dictionary:
        return "（辞書は定義されていません）"

    lines = []

    for key, value in dictionary.items():
        lines.append(f"- {key} → {value}")

    return "\n".join(lines)


def build_system_prompt(config: dict) -> str:
    """システムプロンプトを構築する（YAMLで未定義の場合はデフォルト埋め込みを使用）．"""
    # YAML側に prompt 指定があればそれを使い、なければ埋め込みプロンプトを使用
    prompt = config.get("prompt") or DEFAULT_SYSTEM_PROMPT_TEMPLATE

    dictionary = config.get("dictionary", {})
    dictionary_text = build_dictionary_text(dictionary)

    return prompt.replace("{{DICTIONARY}}", dictionary_text)


def make_client(config: dict) -> OpenAI:
    """OpenAI互換APIクライアントを作成する．"""
    server = config.get("server", {})

    base_url = server.get("base_url")
    api_key = server.get("api_key")

    if not base_url:
        raise ValueError(
            "tts_filter.yaml の server.base_url が定義されていません．"
        )

    if not api_key:
        raise ValueError(
            "tts_filter.yaml の server.api_key が定義されていません．"
        )

    timeout = httpx.Timeout(connect=float(server.get("connect_timeout", 5)),
                            read=float(server.get("read_timeout", 30)),
                            write=float(server.get("write_timeout", 30)), pool=5.0)
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)


def _kanji_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text))


def _suspicious_change(original: str, converted: str) -> str | None:
    """危険な全文ひらがな化や欠落を検出する．誤検出を避けて保守的に判定．"""
    if not converted.strip():
        return "空の出力"
    orig_n = len(original.strip())
    result_n = len(converted.strip())
    if orig_n >= 40 and result_n < orig_n * 0.58:
        return "出力が極端に短い"
    if orig_n >= 40 and result_n > orig_n * 2.0:
        return "出力が極端に長い"
    before = _kanji_count(original)
    after = _kanji_count(converted)
    if before >= 8 and after < before * 0.65:
        return "漢字が大幅に減少（過剰なひらがな化の疑い）"
    return None


def _emit_filter_progress(metrics: dict, progress_callback=None) -> None:
    """単独実行時は標準出力，組み込み時は指定先へ進捗を渡す．"""
    if progress_callback is not None:
        progress_callback(metrics)
    else:
        print('[LLM_PROGRESS] ' + json.dumps(metrics, ensure_ascii=False), flush=True)


def transform(
    client: OpenAI,
    model: str,
    system_prompt: str,
    text: str,
    generation: dict,
    progress_callback=None,
) -> str:
    """一つの段落を変換し，異常時に厳格な指示で再試行する．"""
    if not text.strip():
        return text
    leading = text[:len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()):]
    core_text = text.strip()

    def request(strict: bool) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        if strict:
            messages.append({"role": "system", "content": (
                "前回の変換は本文保持に失敗しました。漢字のひらがな化・"
                "省略・言い換えを禁止します。日本語の文は原文のまま残し，"
                "英字・技術表記の読みが必要な箇所だけを変換してください。"
                "変換後の本文だけを出力してください。"
            )})
        messages.append({"role": "user", "content": core_text})
        kwargs = {
            "model": model,
            "messages": messages,
        }
        effort = generation.get("reasoning_effort", "low")
        if effort != "auto":
            kwargs["extra_body"] = {"reasoning_effort": effort}
        for key in ("temperature", "max_tokens", "top_p", "seed"):
            if key in generation:
                kwargs[key] = generation[key]
        started = time.monotonic()
        reasoning_chars = content_chars = 0
        parts = []
        finish_reason = None
        usage = None
        max_chars = int(generation.get("max_output_chars", 20000))
        last_progress = 0.0
        def report_progress(force=False):
            nonlocal last_progress
            now = time.monotonic()
            if force or now - last_progress >= 1.0:
                metrics = {
                    "task": "TTSヨミ変換", "state": "LLM受信中",
                    "reasoning_chars": reasoning_chars, "content_chars": content_chars,
                    "total_chars": reasoning_chars + content_chars,
                    "limit_chars": max_chars,
                    "elapsed_sec": round(now - started, 1),
                }
                _emit_filter_progress(metrics, progress_callback)
                last_progress = now
        report_progress(force=True)
        try:
            with client.chat.completions.create(**kwargs, stream=True,
                    stream_options={"include_usage": True}) as stream:
                for event in stream:
                    if getattr(event, "usage", None) is not None:
                        usage = event.usage
                    for choice in event.choices:
                        delta = choice.delta
                        r = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None) or ""
                        c = delta.content or ""
                        reasoning_chars += len(r)
                        content_chars += len(c)
                        if reasoning_chars + content_chars > max_chars:
                            raise RuntimeError(f"TTSヨミ変換のLLM出力が{max_chars}文字を超過")
                        if c:
                            parts.append(c)
                        report_progress()
                        if choice.finish_reason is not None:
                            finish_reason = choice.finish_reason
            if finish_reason != "stop":
                raise RuntimeError(f"LLMストリーム異常終了: {finish_reason}")
            result = "".join(parts).strip()
            if not result:
                raise RuntimeError("LLMから空の応答が返されました．")
            return result
        finally:
            report_progress(force=True)
            tokens = (f"prompt_tokens={usage.prompt_tokens} completion_tokens={usage.completion_tokens} total_tokens={usage.total_tokens}"
                      if usage else "prompt_tokens=N/A completion_tokens=N/A total_tokens=N/A")
            print(f"[LLM] task=tts_filter reasoning_chars={reasoning_chars} content_chars={content_chars} "
                  f"total_chars={reasoning_chars+content_chars} {tokens} elapsed_sec={time.monotonic()-started:.2f}",
                  file=sys.stderr, flush=True)

    last_reason = ""
    for attempt in range(2):
        result = request(strict=attempt > 0)
        last_reason = _suspicious_change(core_text, result) or ""
        if not last_reason:
            return leading + result + trailing
        print(f"[TTS_FILTER WARN] 変換異常（試行{attempt+1}）: {last_reason}", file=sys.stderr)
    # 原文へのフォールバックは行わず，生成ジョブ全体を失敗として扱う．
    raise RuntimeError(f"TTSヨミ変換の検証に失敗しました（再試行後）: {last_reason}")


def split_paragraphs(text: str) -> list[str]:
    """空行を単位として文章を分割する（従来仕様）．"""
    paragraphs = []
    current = []
    for line in text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def transform_text(
    client: OpenAI,
    model: str,
    system_prompt: str,
    text: str,
    generation: dict,
    progress_callback=None,
) -> str:
    """空行で区切った段落ごとに変換し，段落内部は分割しない．"""
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return text
    converted = []
    for paragraph_index, paragraph in enumerate(paragraphs, 1):
        # 各段落のLLM呼び出しは独立しており，文字数・時間も段落単位で集計する．
        paragraph_total = len(paragraphs)
        def paragraph_progress(metrics, index=paragraph_index, total=paragraph_total):
            event = dict(metrics)
            event["paragraph_index"] = index
            event["paragraph_total"] = total
            event["task"] = f"TTSヨミ変換（段落 {index} / {total}）"
            _emit_filter_progress(event, progress_callback)
        converted.append(transform(client, model, system_prompt, paragraph, generation,
                                   progress_callback=paragraph_progress))
    return "\n\n".join(converted)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LLMを利用した日本語TTS用読み変換フィルタ"
    )

    parser.add_argument(
        "-c",
        "--config",
        default="tts_filter.yaml",
        help="設定ファイル（デフォルト: tts_filter.yaml）",
    )

    parser.add_argument(
        "-i",
        "--input",
        help="入力ファイル．指定しない場合は標準入力から読む",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="出力ファイル．指定しない場合は標準出力へ出力",
    )

    args = parser.parse_args()

    try:
        config_path = Path(args.config).resolve()
        config = load_config(config_path)

        server = config.get("server", {})
        model = server.get("model")

        if not model:
            raise ValueError(
                "tts_filter.yaml の server.model が定義されていません．"
            )

        generation = config.get("generation", {})
        system_prompt = build_system_prompt(config)
        client = make_client(config)

        if args.input:
            input_path = Path(args.input)

            with input_path.open("r", encoding="utf-8") as f:
                text = f.read()
        else:
            text = sys.stdin.read()

        result = transform_text(
            client=client,
            model=model,
            system_prompt=system_prompt,
            text=text,
            generation=generation,
        )

        if args.output:
            output_path = Path(args.output)

            with output_path.open("w", encoding="utf-8") as f:
                f.write(result)
                f.write("\n")
        else:
            print(result)

        return 0

    except KeyboardInterrupt:
        return 130

    except Exception as e:
        print(
            f"tts_filter: エラー: {e}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
