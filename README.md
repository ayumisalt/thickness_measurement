# 顕微鏡画像を用いた飛跡太さ・体積解析

顕微鏡の z-stack 画像から飛跡の太さを測定し、飛跡に沿った累積体積と飛程（range）の関係を解析するためのツールです。既知の電荷を持つ試料を基準データとして、未知試料との比較にも利用できます。

Python版とC++17/ROOT版を提供しています。両者は共通の入力・出力形式を使用します。

## 主な機能

- 顕微鏡 z-stack から飛跡に垂直な輝度プロファイルを抽出
- `tanh(Gaussian)` モデルによる飛跡幅・分解能の推定
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
- C++17対応コンパイラ
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

同じtrack IDに3点以上が記録されている場合、先頭点と末尾点を飛跡の端点として使用します。点の並び順が飛程の原点と方向を決めます。

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

既定では800 nmを超えるwidthを除外します。閾値は変更できます。

```bash
python track_volume.py \
  results/all_track_thickness.txt \
  -o results/volume_unknown.txt \
  --maximum-width-nm 900
```

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

`--scores-output` を指定すると、未知試料の各trackについて以下をCSVへ出力します。

- volume–range直線の傾き
- 基準試料に対する傾き比
- 基準試料からのz-score
- 3σ範囲との整合性

## C++17 / ROOT版の使い方

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
  -o results/volume_unknown_root.txt

./build/volume_range_root \
  results/volume_alpha_reference.txt \
  results/volume_unknown_root.txt \
  -o results/volume_range_root.pdf \
  --scores-output results/charge_comparison_root.csv
```

`summarize_result_root` には入力ファイルを明示的に指定してください。directoryの再帰検索が必要な場合はPython版を使用するか、Shell側で入力ファイルを展開します。

## 出力形式

### Thickness測定結果

```text
# columns: track_id distance_um resolution_nm width_nm sigma_nm
```

- `distance_um`: track先頭点からの距離 [µm]
- `resolution_nm`: fitting曲線の10–90 % edge距離 [nm]
- `width_nm`: fitting曲線の左右変曲点間隔 [nm]
- `sigma_nm`: fittingしたGaussian成分のσ [nm]

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

## 利用上の注意

volume–range比較は、未知trackが基準試料とどの程度整合するかを評価するための指標です。出力されるz-scoreや3σ判定だけで電荷を確定するものではありません。

電荷同定へ使用する場合は、複数の既知電荷試料を用いた較正、測定条件による系統誤差、track方向、width cut、試料ごとの収縮率を評価してください。
