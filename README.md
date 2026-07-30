# Microscope track thickness measurement

顕微鏡z-stackに記録された飛跡の横幅を測定し、累積体積–range関係を既知charge sampleと比較する解析です。全工程にPython版とC++17/ROOT版があります。

## 解析フロー

```text
image.json + PNG stack + track endpoints
                   |
                   v
          track_thickness
     (distance, resolution, width)
                   |
                   v
          summarize_result
      (複数areaのtrack IDを統合)
                   |
                   v
            track_volume
       (円柱近似による累積体積)
                   |
                   v
            volume_range
 (既知charge referenceとの傾き比較)
```

数式、単位、入力列、復元した解析意図は [docs/analysis.md](docs/analysis.md) に記載しています。

## 推奨環境: Miniconda / Miniforge

Python 3.12、C++17、ROOT 6.32以上6系、OpenCV 4.8以上を同じconda-forge環境に揃えます。system ROOTとsystem compilerを混ぜると、特にmacOSではClingとC++標準libraryの不整合が起きやすいため、C++/ROOT版ではこの方法を推奨します。

```bash
conda env create -f environment.yml
conda activate thickness-measurement
python -m pytest
```

### pyenv + venv（Python版のみ）

```bash
pyenv install 3.12.9
pyenv local 3.12.9
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

ROOT/OpenCV C++開発fileをpyenvは管理しないため、C++版も使う場合はconda環境を利用してください。

## Sample data

入力は次の3種類です。

- `sample_data/AREA00_alpha_0000/image.json`: metadata
- 同directoryの`0000.png`〜`0599.png`: z-stack 600枚
- `sample_data/AREA00_alpha_0000/tracks_endpoints.txt`: 端点だけに整理した初期値

PNG 600枚は合計約712 MiBあるため `.gitignore` 対象です。現在の作業directoryには保持されますが、remote repositoryへ含める場合はGit LFSまたは実験data repositoryを準備してください。metadataとtrack textは通常のGit管理対象です。

## Python版

### 1. Thickness measurement

```bash
python track_thickness.py \
  sample_data/AREA00_alpha_0000/image.json \
  sample_data/AREA00_alpha_0000/tracks_endpoints.txt \
  -o results/AREA00_track_thickness.txt
```

現在の多点ファイルも直接指定でき、その場合はtrackごとの先頭・末尾だけを端点として使います。

```bash
python track_thickness.py \
  sample_data/AREA00_alpha_0000/image.json \
  sample_data/AREA00_alpha_0000/image.jsonTrackForUguisFitting.txt \
  -o results/AREA00_track_thickness.txt
```

確認のため1 trackだけ測る場合:

```bash
python track_thickness.py \
  sample_data/AREA00_alpha_0000/image.json \
  sample_data/AREA00_alpha_0000/tracks_endpoints.txt \
  --track-id 1 -o results/track1_thickness.txt
```

### 2. 複数areaの集計

スペルミスのあった旧 `summrize_result.py` は `summarize_result.py` に改名しました。file、directory、globを入力にできます。

```bash
python summarize_result.py \
  'data/AREA*/track_thickness.txt' \
  -o results/all_track_thickness.txt
```

Shellがglobを展開しないよう引用符を付けても、script側で展開します。directoryを渡すと配下の `track_thickness.txt` を再帰検索します。既定では各入力のtrack IDを全体で一意な1始まりIDへ振り直します。

### 3. Cumulative volume

```bash
python track_volume.py \
  results/all_track_thickness.txt \
  -o results/volume_unknown.txt
```

既定のwidth cutは800 nmです。変更する場合は `--maximum-width-nm` を使います。

### 4. Volume–range visualization / comparison

Referenceだけを描画:

```bash
python volume_range.py \
  results/volume_alpha_reference.txt \
  -o results/volume_range_reference.png
```

未知sampleを比較し、trackごとの傾きscoreも保存:

```bash
python volume_range.py \
  results/volume_alpha_reference.txt \
  results/volume_unknown.txt \
  -o results/volume_range_comparison.png \
  --scores-output results/charge_comparison.csv
```

## C++17 / ROOT版

Conda環境を有効化してbuildします。

```bash
cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$CONDA_PREFIX"
cmake --build build
```

対応するcommandは次の通りです。入力・出力形式と主要optionはPython版と同じです。

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

C++の `summarize_result_root` は明示されたfile列を受け取ります。directory/globの再帰展開が必要な場合はPython版集計を使うか、Shell側で展開してください。

## Test

Python unit test:

```bash
python -m pytest
# pytest未導入の最小環境では:
python -m unittest discover -s tests -v
```

C++ build後のquick check:

```bash
./build/track_volume_root results/all_track_thickness.txt \
  -o results/volume_cpp_check.txt
```

PythonとC++/ROOT版は同じ列・単位・fit modelを使いますが、SciPyとROOT Minuitのoptimizer差によりfit結果は完全なbit一致にはなりません。
