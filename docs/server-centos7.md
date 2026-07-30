# CentOS 7解析サーバーでの環境構築

対象サーバー:

- CentOS 7 / glibc 2.17 / x86_64
- micromamba 2.6系
- ユーザーごとに独立した `$HOME/micromamba` を使用

## 1. TLS証明書の確認

micromambaの `ssl_verify` を無効化して環境を作成しないこと。サーバー管理者が管理する最新のCA bundle、または組織から配布されたCA bundleを使用する。

```bash
micromamba config list | grep ssl_verify
```

CA bundleが `/path/to/ca-bundle.pem` にある場合:

```bash
micromamba config set ssl_verify /path/to/ca-bundle.pem
curl --cacert /path/to/ca-bundle.pem \
  -fsSI https://conda.anaconda.org/conda-forge/ |
  sed -n '1,5p'
```

`ssl_verify: false` は使用しない。複数ユーザーで運用する場合は、全ユーザーが読める共通パスへCA bundleを配置するか、OSの `ca-certificates` を管理者が更新する。

## 2. micromambaの初期化

同じサーバーの複数ユーザーで使用する場合、動作確認済みのmicromamba binaryとCA bundleを共通の読み取り専用directoryへ配置できる。

```bash
SHARED_RUNTIME=/shared/path/to/thickness-measurement/runtime

export THICKNESS_MAMBA_EXE="$SHARED_RUNTIME/bin/micromamba"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
SHARED_CA="$SHARED_RUNTIME/certs/ca-certificates-2026.5.20.pem"

env -u MAMBA_EXE \
  "$THICKNESS_MAMBA_EXE" \
  --root-prefix "$MAMBA_ROOT_PREFIX" \
  config set ssl_verify "$SHARED_CA"
```

micromamba 2.6系では、実行ファイルのbasenameが `micromamba` または `mamba` でなければ `run` や `activate` が正常に動作しない。また、symlinkは実体のversion付きファイル名へ解決されるため使用できない。共有directoryには `micromamba` という名前のbinaryコピーを用意する。

```bash
cd "$SHARED_RUNTIME/bin"
install -m 0755 micromamba-2.6.2 micromamba
```

各ユーザーは自分のhome directoryに環境とpackage cacheを持つ。`SHARED_RUNTIME`、`THICKNESS_MAMBA_EXE`、`MAMBA_ROOT_PREFIX` はshellを開くたびに必要になるため、ユーザー固有の設定fileまたは `~/.zshrc` に保存する。`micromamba info` の `envs directories` が自分のhome directory以下になっていることを確認する。

## 3. 環境作成

リポジトリへ移動する。`environment-linux-64.lock` がある場合は、同じサーバーで動作確認済みの全packageを固定したlock fileを優先する。

```bash
cd "$HOME/thickness_measurement"

env -u MAMBA_EXE \
  "$THICKNESS_MAMBA_EXE" \
  --root-prefix "$MAMBA_ROOT_PREFIX" \
  create --name thickness-measurement \
  --file environment-linux-64.lock
```

lock fileがまだ作成されていない場合だけ、CentOS 7用の直接依存versionを指定したYAMLから作成する。

```bash
env -u MAMBA_EXE \
  "$THICKNESS_MAMBA_EXE" \
  --root-prefix "$MAMBA_ROOT_PREFIX" \
  create --file environment-server.yml
```

サーバー共通の `PYTHONPATH` や `ROOTSYS` が設定されている場合、activateしただけではsystem packageが混入する可能性がある。以降のテスト、build、解析には `scripts/run-in-env.sh` を使用する。

作成後の確認:

```bash
scripts/run-in-env.sh python --version
scripts/run-in-env.sh python -c \
  'import numpy, scipy, cv2, matplotlib; print(
    "numpy", numpy.__version__,
    "scipy", scipy.__version__,
    "opencv", cv2.__version__,
    "matplotlib", matplotlib.__version__
  )'
scripts/run-in-env.sh root-config --version
scripts/run-in-env.sh root-config --cflags
scripts/run-in-env.sh cmake --version
scripts/run-in-env.sh c++ --version
```

## 4. Python版のテスト

```bash
cd "$HOME/thickness_measurement"
scripts/run-in-env.sh python -m pytest
```

## 5. C++/ROOT版のビルド

ROOT 6.40のconda-forge buildはC++20を使用する。プロジェクトのCMake設定は `ROOT_CXX_STANDARD` を読み、ROOTと同じC++標準を自動選択する。

```bash
cd "$HOME/thickness_measurement"

ENV_PREFIX="$MAMBA_ROOT_PREFIX/envs/thickness-measurement"

scripts/run-in-env.sh cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$ENV_PREFIX"

scripts/run-in-env.sh cmake --build build
```

設定時に次のような表示が出ることを確認する。

```text
-- Using C++20 to match ROOT
```

## 6. 完全なlinux-64 lock fileの生成

最初の環境作成とテストが成功した後、間接依存を含むpackage URLを固定する。

```bash
env -u MAMBA_EXE \
  "$THICKNESS_MAMBA_EXE" \
  --root-prefix "$MAMBA_ROOT_PREFIX" \
  env export \
  --name thickness-measurement \
  --explicit > environment-linux-64.lock
```

`environment-linux-64.lock` をリポジトリへcommitする。以降、同じサーバーの別ユーザーは次のコマンドで同一package集合を再現できる。

```bash
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
SHARED_RUNTIME=/shared/path/to/thickness-measurement/runtime
export THICKNESS_MAMBA_EXE="$SHARED_RUNTIME/bin/micromamba"

cd "$HOME/thickness_measurement"
env -u MAMBA_EXE \
  "$THICKNESS_MAMBA_EXE" \
  --root-prefix "$MAMBA_ROOT_PREFIX" \
  create \
  --name thickness-measurement \
  --file environment-linux-64.lock
```

## 7. 環境を有効化しない実行方法

batch処理やcronでも同じwrapperを使用する。wrapperは次のsite-wide環境変数を除外する。

- `PYTHONPATH`, `PYTHONHOME`
- `ROOTSYS`
- compiler include/library検索path
- `CMAKE_PREFIX_PATH`, `PKG_CONFIG_PATH`
- `LD_LIBRARY_PATH`

```bash
export THICKNESS_MAMBA_EXE="$SHARED_RUNTIME/bin/micromamba"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"

scripts/run-in-env.sh python track_thickness.py --help

scripts/run-in-env.sh ./build/track_volume_root --help
```

## 8. 複数areaの一括処理

`scripts/process-dataset.py` は、指定patternに一致する全areaについて以下を順に実行する。

1. 飛跡太さ測定
2. 全areaのtrack IDを統合
3. 累積体積を計算
4. volume–range plotを作成

Python版:

```bash
scripts/run-in-env.sh python scripts/process-dataset.py \
  /path/to/dataset-parent \
  --pattern 'AREA00_alpha_*' \
  --backend python \
  --thickness-dir results/alpha-python/per-area \
  --results-dir results/alpha-python
```

C++/ROOT版:

```bash
scripts/run-in-env.sh python scripts/process-dataset.py \
  /path/to/dataset-parent \
  --pattern 'AREA00_alpha_*' \
  --backend root \
  --build-dir build \
  --thickness-dir results/alpha-root/per-area \
  --results-dir results/alpha-root
```

`--thickness-dir` を指定すると、入力area directoryを変更せず、areaごとの `track_thickness.txt` を指定directoryの下へ保存する。共有データを複数ユーザーで読み取る場合や、Python版とROOT版を別々に保存する場合は、この指定を推奨する。

既存の各areaの `track_thickness.txt` を再利用し、集計・体積・可視化だけを再実行する場合:

```bash
scripts/run-in-env.sh python scripts/process-dataset.py \
  /path/to/dataset-parent \
  --skip-thickness \
  --results-dir results/alpha-replot
```

実行前に対象fileとcommandを確認する場合は `--dry-run` を付ける。
