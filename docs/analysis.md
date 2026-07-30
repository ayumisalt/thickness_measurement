# 解析の意図と計算内容

## 復元した処理フロー

1. `image.json` から画像サイズ、stage座標とpixel座標のaffine変換、各PNGのz座標を読む。
2. track初期値の先頭点と末尾点を直線飛跡の端点とする。中間点がある入力でも端点だけを利用する。
3. 端点間を既定1 µm間隔で走査する。
4. 各位置で、端点zを線形補間した予測焦点面の前後25 frameを調べる。Gaussian blur画像から原画像を引いた像の局所和が最大のframeを採用する。
5. 飛跡に垂直な輝度profileを取得し、次式をfitする。

   `I(x) = H tanh(S exp(-(x - μ)² / (2σ²)))`

6. fit曲線の10–90 % edge距離を `resolution_nm`、左右の変曲点間隔を `width_nm` とする。
7. widthを円柱の直径とみなし、各1 µm区間の `π(width/2)² Δx` を累積して飛跡体積を得る。
8. 既知chargeのreference sampleについてvolume–rangeの傾きを作り、未知trackの傾きと比較する。

## 座標と単位

- JSONおよびtrack初期値のstage座標は mm。
- `AffineP2S` はpixel中心からstage座標への2×2変換として扱う。
- `# Shrink: 1.9` のtrack入力では、z値を1.9で割ってJSONのacquisition zへ戻す。
- thickness出力の距離は µm、resolution/width/sigmaは nm。
- volume出力のrangeは µm、volumeは µm³。

## 入力track形式

Uguis由来の両形式に対応する。

```text
# Shrink: 1
track_id x_mm y_mm z_mm
```

```text
# Shrink: 1.9
event_id track_id x_mm y_mm z_mm_shrunk
```

同一track IDに3点以上あっても、解析では最初と最後の点だけを使う。点の順序がrangeの原点と向きを決めるため、停止点から測りたい場合は停止点を先頭に置く。

## 出力形式

Thickness:

```text
# columns: track_id distance_um resolution_nm width_nm sigma_nm
```

Volume:

```text
# columns: track_id range_um cumulative_volume_um3
```

`track_volume` は既定で800 nmを超えるwidthをfit失敗候補として除外する。除外区間を次の有効点へまとめて積分しないよう、距離位置は除外時にも更新する。

## Charge identificationについて

元コードに存在したのは、既知alphaデータをrange 5 µmごとにまとめ、volume–range平面へ未知trackを重ねる処理であり、chargeを確定する学習済み分類器ではなかった。整理後の `volume_range` もこの意図を保ち、referenceの原点固定直線fitに対する各candidate trackの傾き比とz-scoreをCSVへ出せるようにした。

`consistent_with_reference_3sigma` は品質確認用の統計的目安であり、物理的なcharge同定を単独で保証しない。chargeラベルとして運用する前に、複数の既知charge sample、測定条件ごとのsystematic uncertainty、track方向、width cutの妥当性を検証する必要がある。

## 旧コードからの主な修正

- 多点入力の最初の2点だけを使っていた処理を、先頭・末尾の端点利用へ変更。
- 固定5 track、連続ID、固定絶対pathを廃止。
- `summrize_result.py` を `summarize_result.py` に改名。
- 集計時のID加算不具合を、入力ファイルとlocal track IDの明示mappingへ変更。
- 位置番号×0.1という固定換算を廃止し、thickness段階から距離µmを出力。
- 画像全体600枚をtrackごとに保持せず、飛跡周辺ROIと必要焦点frameだけをcache。
- `alpha_point.py`、`resolution_check.py`、`resolution_opt.py`、`hist_width.py` は現行pipelineから参照されず、固定装置寸法・固定pathを含む実験コードだったため削除。
- 旧ROOT macro `volume_range.c` は引数対応した `cpp/src/volume_range.cpp` で置換。
