# ポインタモード（3階層）

## 設定

- プレゼンテーション標準: `pointer_default_mode`（`static` / `active` / `hidden`）．未設定なら `static`．
- スライド: `pointer_slide_modes` のスライド番号（文字列）による上書き．未指定なら継承．
- 文: `<page>_align.json` の `alignments[]` に保存する `pointer_mode`．未指定または `inherit` は上位を継承．
- 優先順位は **文 > スライド > プレゼンテーション**．

## 操作

プレゼンテーション標準はサイドバーの「VLMを活用してポインタ配置を決定する」の直下にあります（Easy/Advanced共通）．スライド設定は「ナレーション修正（詳細）」で変更します．同画面の文ごとの行ではモードと動作パターンを選択できます．最終モードがアクティブでない文の動作パターン欄はグレーアウトし，既存値は保持されます．文ごとに変更した場合は，画面下の「字幕・ポインタ修正を保存」を押してください．

プロジェクト・スライドの設定変更は動画ファイルの再生成を必要とします．**アクティブ動作のLLM自動選択には「保存して字幕・ポインタを再解析」が必要**です．すでに静止モードで解析されたJSONに`motion`がない場合は，アクティブへ切り替えただけでは自動的に動きが決定されず，固定位置が使われます．

再解析すると文ごとの編集内容は生成結果で上書きされ得ます．必要な編集は再解析後に行ってください．

## データ例

`project.json`:

```json
{
  "pointer_default_mode": "static",
  "pointer_slide_modes": {"5": "active", "8": "hidden"}
}
```

`005_align.json` の文要素:

```json
{
  "sentence": "左から右へデータが流れます．",
  "block_id": 2,
  "pointer_mode": "inherit",
  "motion": {"type": "line", "direction": "left_to_right"}
}
```

## 対応動作

LLM は `fixed`，`line`，`ellipse`，`rounded_polygon`，`hidden` を選択します．動作指定は意味的な指定であり，数値座標はbboxからPythonで生成します．`rounded_polygon` は **bboxの角丸矩形による近似** です．三角形など元図形の輪郭を厳密に追跡するものではありません．軌跡生成に失敗した場合は固定位置にフォールバックします．元のbbox自体に対応する対象がない場合はポインタを表示しません．

すべての動作は文の半開区間 `[start,end)` のみ表示します．文が切り替われば旧動作は継続しません．

揺らぎの基本振幅は固定時2px，移動中はその15%（0.3px）です．固定時の揺れは2Hz付近の成分を主体とします．文中の部分的な語単位同期はまだ対応していません．

## テスト

```bash
python3 -m unittest test_pointer_settings -v
python3 -m py_compile app.py slide_lecture.py pointer_motion.py pointer_settings.py
```

本体の依存ライブラリは従来どおり `requirements.txt` から導入してください．

