# 解析の意図と計算内容

## 復元した処理フロー

1. `image.json` から画像サイズ、stage座標とpixel座標のaffine変換、各PNGのz座標を読む。
2. track初期値の全点を順に結び、3D折れ線として近似する。
3. 折れ線の3D累積長を既定1 µm間隔で走査する。各測定点では局所segmentのXY射影に垂直なprofileを取得する。
4. 各位置で、局所segment内で補間したzの前後25 frameを調べる。Gaussian blur画像から原画像を引いた像の局所和が最大のframeを採用する。
5. 横断輝度profileを取得し、次式をfitする。

   `I(x) = H tanh(S exp(-(x - μ)² / (2σ²)))`

6. fit曲線の10–90 % edge距離を `resolution_nm`、左右の変曲点間隔を `width_nm` とする。
7. profile両端の周辺領域から背景noiseを推定し、R²、NRMSE、reduced χ²、p-value、width不確かさを計算する。
8. widthを円柱の直径とみなし、各1 µm区間の `π(width/2)² Δx` を累積して飛跡体積を得る。
9. 既知chargeのreference sampleについてvolume–rangeの傾きを作り、未知trackの傾きと比較する。

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

同一track IDに3点以上ある場合は、全点を通る3D折れ線として扱う。これにより曲がったtrackを端点間の一本の直線とみなして斜めに横断し、widthを過大評価する問題を抑える。点の順序がrangeの原点と向きを決めるため、停止点から測りたい場合は停止点を先頭に置く。

## 出力形式

Thickness:

```text
# columns: track_id distance_um resolution_nm width_nm sigma_nm contrast fit_r2 fit_nrmse reduced_chi2 fit_p_value width_error_nm width_relative_error noise_sigma
```

Volume:

```text
# columns: track_id range_um cumulative_volume_um3
```

`track_volume` は既定ではquality cutを適用しない。cutを指定した場合、不採用となった内部点のwidthは前後の採用点から線形補間する。先頭・末尾側の不採用測定点は出力せず、採用点が2点未満のtrackは解析対象外とする。積分原点から最初の採用点までの区間は、従来の積分定義を保って最初の採用widthを用いる。

χ²とp-valueに用いるnoise σは固定値ではなく、fit対象とは別の近傍profileについて、両端25%を局所track方向へ±0.5 µmサンプリングした背景値から推定する。DoG画像は負値が0へclipされるため、MADと半波整流Gaussianに対するRMS補正の大きい方を使い、量子化floorを1とする。画素間相関やモデルの系統差があるため、p-valueは単独の物理判定ではなくfit診断として扱う。

## Charge identificationについて

元コードに存在したのは、既知alphaデータをrange 5 µmごとにまとめ、volume–range平面へ未知trackを重ねる処理であり、chargeを確定する学習済み分類器ではなかった。整理後の `volume_range` もこの意図を保ち、referenceの原点固定直線fitに対する各candidate trackの傾き比とz-scoreをCSVへ出せるようにした。

referenceの各range binはtrackごとに一度平均してからtrack間の平均と標準偏差を計算する。`--minimum-reference-tracks-per-bin`により、統計数が不足する長飛程binをfitから除外できる。candidateとの差のz-scoreにはreferenceとcandidateの傾き誤差を二乗和で用いる。

`consistent_with_reference_3sigma` は品質確認用の統計的目安であり、物理的なcharge同定を単独で保証しない。chargeラベルとして運用する前に、複数の既知charge sample、測定条件ごとのsystematic uncertainty、track方向、quality cutの妥当性を検証する必要がある。

## 旧コードからの主な修正

- 多点入力を端点間の直線とみなす処理を、全点を使う3D折れ線近似へ変更。
- 固定5 track、連続ID、固定絶対pathを廃止。
- `summrize_result.py` を `summarize_result.py` に改名。
- 集計時のID加算不具合を、入力ファイルとlocal track IDの明示mappingへ変更。
- 位置番号×0.1という固定換算を廃止し、thickness段階から距離µmを出力。
- 画像全体600枚をtrackごとに保持せず、飛跡周辺ROIと必要焦点frameだけをcache。
- `alpha_point.py`、`resolution_check.py`、`resolution_opt.py`、`hist_width.py` は現行pipelineから参照されず、固定装置寸法・固定pathを含む実験コードだったため削除。
- 旧ROOT macro `volume_range.c` は引数対応した `cpp/src/volume_range.cpp` で置換。
