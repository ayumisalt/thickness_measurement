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
# columns: track_id distance_um resolution_nm width_nm sigma_nm contrast fit_r2 fit_nrmse reduced_chi2 fit_p_value width_error_nm width_relative_error noise_sigma theta_deg local_theta_deg
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

## θを揃える場合の定義と制約

θは測定時のacquisition座標、すなわち入力zを`input_shrink`で割った座標で、
track全体の始点と終点の差から`atan2(hypot(Δx, Δy), Δz)`で求める極角とする。
水平は90°。`θfold = min(θ, 180°−θ)`へ折り返し、
`abs(θfold_reference − θfold_candidate) <= X`を満たすtrack全体を採用する。
境界は含む（浮動小数丸め許容1e-10 degree）。z符号反転と点順序反転で採否は変わらない。
これは収縮を戻した物理空間の角度ではなく、画像上の見かけの太さに対応する角度である。

測定結果の14列目に代表θ、15列目に測定位置の局所θを保存する。統合後も保持する。
角度表へexportした場合、埋め込み情報では測定点の局所θfold最小・最大、旧形式から
元座標を参照した場合は全segmentの最小・最大を出力する。track全体の角度cutは
局所segmentへの角度cutではないため、曲がりの大きいtrackでは代表角度の限界がある。
測定と同一座標・Shrinkを使う必要があり、座標を更新した場合はthicknessとの対応を確認する。
15列thicknessは元座標を参照せず角度cutできる。旧形式で角度を補う場合のみ元座標が必要。
別の角度表を使う場合は現在のcombined IDへ生成し直す。欠損角度を推測しない。
始終点が一致するtrackは代表θをnanで保存し、角度cut要求時にエラーとする。
局所θは局所segmentの3D方向から求める。横断profile用のXY方向を近傍segmentから
借りる場合でも、局所θには元のsegmentの方向を保存する。

角度選択後も品質cut・内部width補間・体積積分・track単位bin集計は従来どおり。
採用点数はquality条件を通った実測点、valid track数は2採用点以上のtrackを意味する。
summaryにはvalid trackに属する採用点数も別途出す。CSVの`n_volume_points`は
内部補間を含み、体積上限5 µm³適用後のcandidate fit点数である。
referenceはbin内のtrack間標準偏差を重みに原点固定fitし、candidateは非加重fitする。
報告するslope誤差はfit残差から計算した値で、累積点間・bin間の相関やwidth誤差の
伝播、較正系統誤差を含む総合不確かさではない。

角度幅によるreference slopeの変化と残存統計を併記して、太さの差が角度選択だけで
説明できるかを検討する。角度cutでrange分布や体積上限による選択も変わり得るため、
差の原因を角度に断定せず、z-scoreから物理的chargeを確定しない。

## 旧コードからの主な修正

- 多点入力を端点間の直線とみなす処理を、全点を使う3D折れ線近似へ変更。
- 固定5 track、連続ID、固定絶対pathを廃止。
- `summrize_result.py` を `summarize_result.py` に改名。
- 集計時のID加算不具合を、入力ファイルとlocal track IDの明示mappingへ変更。
- 位置番号×0.1という固定換算を廃止し、thickness段階から距離µmを出力。
- 画像全体600枚をtrackごとに保持せず、飛跡周辺ROIと必要焦点frameだけをcache。
- `alpha_point.py`、`resolution_check.py`、`resolution_opt.py`、`hist_width.py` は現行pipelineから参照されず、固定装置寸法・固定pathを含む実験コードだったため削除。
- 旧ROOT macro `volume_range.c` は引数対応した `cpp/src/volume_range.cpp` で置換。
