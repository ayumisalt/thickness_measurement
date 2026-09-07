# 顕微鏡画像を用いた飛跡太さ・体積解析

顕微鏡の z-stack 画像から飛跡の太さを測定し、飛跡に沿った累積体積と飛程（range）の関係を解析するためのツールです。既知の電荷を持つ試料を基準データとして、未知試料との比較にも利用できます。

Python版とC++/ROOT版を提供しています。両者は共通の入力・出力形式を使用します。C++標準は使用するROOTのbuildに合わせ、C++17またはC++20を自動選択します。

## 主な機能

- 多点trackを3D折れ線として近似し、局所方向に垂直な輝度プロファイルを抽出
- `tanh(Gaussian)` モデルによる飛跡幅・分解能の推定
- R²、NRMSE、χ² p-value、width不確かさなどのfit品質評価
- 複数の撮影領域（area）から得た測定結果の統合
- 飛跡断面を円と仮定した累積体積の計算
- 既知試料と未知試料の volume–range 関係の比較
- 比較結果のプロットおよびtrackごとの傾き・z-scoreのCSV出力

## 解析フロー

```text
image.json + PNG z-stack + track初期値
                    |
                    v
           track_thickness
       距離・分解能・飛跡幅を測定
                    |
                    v
           summarize_result
      複数areaの測定結果をまとめる
                    |
                    v
             track_volume
          累積飛跡体積を計算
                    |
                    v
             volume_range
      既知試料と未知試料を比較・描画
```

計算方法、使用する単位、入出力列の詳細は [解析仕様](docs/analysis.md) を参照してください。

## 必要な環境

推奨構成は以下の通りです。

- Python 3.12
- C++17またはC++20対応コンパイラ
- ROOT 6.32以上の6系
- OpenCV 4.8以上
- CMake 3.20以上

### Miniconda / Miniforge

Python版とC++/ROOT版の両方を使用する場合は、conda-forge環境を推奨します。

```bash
conda env create -f environment.yml
conda activate thickness-measurement
```

macOSでは、ROOT、OpenCV、コンパイラを同じconda環境に揃えることで、ROOT ClingとC++標準ライブラリの不整合を避けやすくなります。

### pyenv + venv

Python版のみ使用する場合は、pyenvとvenvでも環境を構築できます。

```bash
pyenv install 3.12.9
pyenv local 3.12.9

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 入力データ

1つの撮影領域は、次のような構成を想定しています。

```text
AREA00_alpha_0000/
├── image.json
├── 0000.png
├── 0001.png
├── ...
└── tracks_endpoints.txt
```

### 画像メタデータ

`image.json` には以下の情報が必要です。

- 画像サイズ
- pixel座標からstage座標へのaffine変換 `AffineP2S`
- 各PNG画像の相対パス
- 各画像のz座標

PNG画像は8-bit grayscale画像を想定しています。

### Track初期値

4列形式と5列形式に対応しています。

4列形式:

```text
# Shrink: 1
track_id x_mm y_mm z_mm
```

5列形式:

```text
# Shrink: 1.9
event_id track_id x_mm y_mm z_mm_shrunk
```

同じtrack IDに3点以上が記録されている場合、全点を順に結ぶ3D折れ線として使用します。測定位置は折れ線の3D累積長で決まり、横断profileはその位置のsegmentのXY射影に垂直に取得します。点の並び順が飛程の原点と方向を決めます。

## サンプルデータ

`sample_data/AREA00_alpha_0000` にメタデータとtrack初期値を収録しています。

顕微鏡PNG画像600枚は合計約712 MiBあるため、Gitの管理対象には含めていません。解析を実行する際は、`image.json` に記録されたファイル名と一致する画像を同じdirectoryへ配置してください。画像をリモートリポジトリで管理する場合は、Git LFSまたは実験データ用ストレージの利用を推奨します。

## Python版の使い方

### 1. 飛跡太さの測定

```bash
python track_thickness.py \
  sample_data/AREA00_alpha_0000/image.json \
  sample_data/AREA00_alpha_0000/tracks_endpoints.txt \
  -o results/AREA00_track_thickness.txt
```

特定のtrackだけを処理する場合:

```bash
python track_thickness.py \
  sample_data/AREA00_alpha_0000/image.json \
  sample_data/AREA00_alpha_0000/tracks_endpoints.txt \
  --track-id 1 \
  -o results/track1_thickness.txt
```

主なオプション:

- `--spacing-um`: 飛跡に沿った測定間隔。既定値は1 µm
- `--endpoint-margin-um`: 端点から除外する範囲。既定値は2 µm
- `--profile-half-width-um`: 横断プロファイルの片側幅。既定値は2 µm
- `--focus-search-frames`: 予測焦点面の前後で探索するframe数。既定値は25
- `--minimum-contrast`: fitting対象とする最小輝度差。既定値は50
- `--shrink`: trackファイルに記載されたShrink値の上書き

すべてのオプションは次のコマンドで確認できます。

```bash
python track_thickness.py --help
```

### 2. 複数areaの測定結果を統合

入力にはファイル、directory、glob patternを指定できます。

```bash
python summarize_result.py \
  'data/AREA*/track_thickness.txt' \
  -o results/all_track_thickness.txt
```

directoryを指定すると、その配下にある `track_thickness.txt` を再帰的に検索します。既定では、異なる入力ファイル間でtrack IDが重複しないよう、1始まりの連続IDへ振り直します。

元のtrack IDを維持する場合:

```bash
python summarize_result.py \
  data/ \
  -o results/all_track_thickness.txt \
  --keep-track-ids
```

### 3. 累積体積の計算

```bash
python track_volume.py \
  results/all_track_thickness.txt \
  -o results/volume_unknown.txt
```

既定ではwidthやfit品質によるcutを適用しません。fit品質を指定して体積を再計算する場合:

```bash
python track_volume.py \
  results/all_track_thickness.txt \
  -o results/volume_selected.txt \
  --minimum-fit-r2 0.90 \
  --maximum-width-relative-error 0.20
```

指定可能なcutは、contrast、R²、NRMSE、reduced χ²、p-value、width不確かさ、width相対不確かさ、任意のwidth上限、および対称化θの上下限です。バッチ処理では、fit前のprofile選別は`--minimum-contrast`、fit後のcontrast cutは`--minimum-fit-contrast`で別々に指定します。cutで除外された内部測定点は、前後の採用点からwidthを線形補間して体積積分するため、その区間が体積ゼロとして失われることはありません。先頭・末尾側の不採用測定点は出力せず、採用点が2点未満のtrackは除外します。

### 4. Volume–rangeの可視化

基準試料だけを描画する場合:

```bash
python volume_range.py \
  results/volume_alpha_reference.txt \
  -o results/volume_range_reference.png
```

未知試料を基準試料と比較する場合:

```bash
python volume_range.py \
  results/volume_alpha_reference.txt \
  results/volume_unknown.txt \
  -o results/volume_range_comparison.png \
  --scores-output results/charge_comparison.csv
```

fit-quality cutを可視化・有意度解析の段階で変更する場合は、volumeではなくthicknessファイルを直接入力します。画像profileのfitをやり直す必要はありません。

```bash
python volume_range.py \
  results/reference/all_track_thickness_python.txt \
  results/candidate/all_track_thickness_python.txt \
  --input-type thickness \
  --minimum-fit-r2 0.90 \
  --maximum-width-relative-error 0.20 \
  --minimum-reference-tracks-per-bin 10 \
  --scores-output results/charge_comparison.csv \
  -o results/volume_range_comparison.png
```

`--minimum-fit-p-value 0.01`のようにp-valueによるcutも追加できます。p-valueはprofile周辺の背景noise推定とモデルが妥当な場合のgoodness-of-fit指標であり、単独の採否判定ではなくR²やwidth相対不確かさと併用してください。

p-value cutには、13列目に`noise_sigma`を含む現在のthickness出力が必要です。`noise_sigma`を含まない入力は、`track_thickness`から再生成してください。

`--scores-output` を指定すると、未知試料の各trackについて以下をCSVへ出力します。

- volume–range直線の傾き
- 基準試料に対する傾き比
- 基準試料の傾き誤差だけを用いるreference-only z-score
- 基準・未知試料双方の傾き誤差を用いるz-score
- 上記の合成不確かさによる3σ範囲との整合性

## 角度情報の保存と事後cut

PNGから太さを測定すると、15列thicknessの末尾に`theta_deg`（track始点→終点）と
`local_theta_deg`（測定位置のsegment）を保存します。zは測定時のShrinkで割った
acquisition座標を使い、水平は90°です。統合後も角度列を保持するため、
このthicknessファイルだけをダウンロードすれば、元座標やPNGなしで角度cutを変更できます。
旧5〜13列も読み込めますが、角度は欠損値となり、角度cut時には明示的にエラーにします。

角度cutは`min(θ, 180°−θ)`を使うtrack単位の選択です。75°と105°を同じ角度として扱います。
局所角度は診断用で、このcutには使用しません。quality cutと同じCLI/APIに統合しています。

```bash
python track_volume.py results/all_track_thickness.txt \
  --minimum-fit-r2 0.90 --maximum-width-relative-error 0.20 \
  --minimum-theta-deg 30 --maximum-theta-deg 45 \
  -o results/volume_theta30_45.txt
```

同じ上下限optionを`volume_range.py --input-type thickness`、`scripts/process-dataset.py`、
C++版にも指定できます。バッチ処理のcutは測定後のvolume/plotにのみ適用し、
thicknessにはcut前の全fit成功点と角度を保存します。将来のcut変更に画像のrefitは不要です。

candidateが1 trackの場合、その角度に対してreferenceを±X°に揃えられます。

```bash
python volume_range.py \
  results/reference/all_track_thickness_python.txt results/candidate/track_thickness.txt \
  --input-type thickness --minimum-fit-r2 0.90 --maximum-width-relative-error 0.20 \
  --theta-window-deg 5 --minimum-reference-tracks-per-bin 10 \
  --scores-output results/candidate/scores_theta5.csv \
  -o results/candidate/comparison_theta5.png
```

`volume_range_root`にも同じoptionを指定できます。±5°・±10°・±15°と角度cutなしを、
基本cut／p≥0.01追加の8条件で一括比較する場合:

```bash
python scripts/compare-theta.py \
  results/20260706-alpha-python/all_track_thickness_python.txt \
  results/20260707-alpha-python/all_track_thickness_python.txt \
  --candidate results/candidate_001/track_thickness.txt \
  --output-dir results/alpha_theta_comparison_20260907
```

出力directoryは新規名にしてください。統合text、角度表・provenance、条件別PNG/score CSV、
`comparison_summary.csv`、`reference_bins.csv`、`selected_reference_tracks.csv`、
`manifest.json`を保存します。10 track以上のreference binが2個未満なら
`insufficient_reference_bins`と記録し、その条件のfit/plotは生成しません。
体積上限は従来の5 µm³（reference/candidate両方のfit点に適用）、reference binは
0–30 µmの5 µm幅です。上限依存性は`--maximum-volume-um3`を変え、別directoryで確認できます。

旧13列で角度を取得する場合は、元座標が参照可能なmachineで`track_angles.py INPUT -o angles.txt`
を実行できます。`source_map`を再帰的に辿り、測定時の座標とShrinkから角度表を作ります。
移動したpathは`--path-map /old/root=/new/root`を繰り返して対応させます。
15列では埋め込み角度を優先し、元座標は不要です。
比較CLIの`--reference-angles`／`--candidate-angles`で別の角度表を指定すると、そちらを優先します。
一括比較では`--candidate-angles`で旧candidateの角度表を渡せます。
別の角度表を使う際は、表のIDを比較入力に一致させ、再統合後は表も再生成してください。

## C++ / ROOT版の使い方

### ビルド

conda環境を有効化してからビルドします。

```bash
cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$CONDA_PREFIX"
cmake --build build
```

### 実行

```bash
./build/track_thickness_root \
  sample_data/AREA00_alpha_0000/image.json \
  sample_data/AREA00_alpha_0000/tracks_endpoints.txt \
  -o results/AREA00_track_thickness_root.txt

./build/summarize_result_root \
  results/AREA00_track_thickness_root.txt \
  -o results/all_track_thickness_root.txt

./build/track_volume_root \
  results/all_track_thickness_root.txt \
  -o results/volume_unknown_root.txt \
  --minimum-fit-r2 0.90 \
  --maximum-width-relative-error 0.20

./build/volume_range_root \
  results/reference/all_track_thickness_root.txt \
  results/candidate/all_track_thickness_root.txt \
  --input-type thickness \
  --minimum-fit-r2 0.90 \
  --maximum-width-relative-error 0.20 \
  --minimum-reference-tracks-per-bin 10 \
  -o results/volume_range_root.pdf \
  --scores-output results/charge_comparison_root.csv
```

`summarize_result_root` には入力ファイルを明示的に指定してください。directoryの再帰検索が必要な場合はPython版を使用するか、Shell側で入力ファイルを展開します。

## 出力形式

### Thickness測定結果

```text
# columns: track_id distance_um resolution_nm width_nm sigma_nm contrast fit_r2 fit_nrmse reduced_chi2 fit_p_value width_error_nm width_relative_error noise_sigma theta_deg local_theta_deg
```

- `distance_um`: track先頭点からの距離 [µm]
- `resolution_nm`: fitting曲線の10–90 % edge距離 [nm]
- `width_nm`: fitting曲線の左右変曲点間隔 [nm]
- `sigma_nm`: fittingしたGaussian成分のσ [nm]
- `contrast`: 横断profileの最大値−最小値
- `fit_r2`: 決定係数R²
- `fit_nrmse`: RMSEをcontrastで規格化した値
- `reduced_chi2`: 背景noise推定を用いたreduced χ²
- `fit_p_value`: χ² goodness-of-fit p-value
- `width_error_nm`: fit covarianceから伝播したwidth不確かさ [nm]
- `width_relative_error`: `width_error_nm / width_nm`
- `noise_sigma`: profile両端周辺から推定した画素noise
- `theta_deg`: acquisition座標でのtrack始点→終点の極角 [degree, 0–180]
- `local_theta_deg`: 測定位置のsegmentの極角 [degree, 0–180]

### 累積体積

```text
# columns: track_id range_um cumulative_volume_um3
```

- `range_um`: track先頭点からの距離 [µm]
- `cumulative_volume_um3`: 累積体積 [µm³]

## テスト

Python版:

```bash
python -m pytest
```

pytestを使用しない場合:

```bash
python -m unittest discover -s tests -v
```

C++版はビルド後、任意のPython版出力を使って確認できます。

```bash
./build/track_volume_root \
  results/all_track_thickness.txt \
  -o results/volume_cpp_check.txt
```

Python版はSciPy、C++/ROOT版はROOT Minuitをfittingに使用するため、結果は完全なbit一致にはなりません。

CentOS 7解析サーバーでのmicromamba環境、TLS設定、`environment-linux-64.lock` による複数ユーザー間の再現方法は [サーバー環境構築手順](docs/server-centos7.md) を参照してください。

共有サーバーでsystem PythonやROOTの環境変数が設定されている場合は、`scripts/run-in-env.sh` を使用して解析環境を分離できます。

複数の撮影areaを一括処理する場合は `scripts/process-dataset.py` を使用できます。Python版とC++/ROOT版を `--backend` で選択でき、太さ測定からvolume–range plotの作成までを連続して実行します。

## 利用上の注意

volume–range比較は、未知trackが基準試料とどの程度整合するかを評価するための指標です。出力されるz-scoreや3σ判定だけで電荷を確定するものではありません。

電荷同定へ使用する場合は、複数の既知電荷試料を用いた較正、測定条件による系統誤差、track方向、width cut、試料ごとの収縮率を評価してください。
