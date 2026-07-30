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

MAMBA_EXE="$SHARED_RUNTIME/bin/micromamba"
SHARED_CA="$SHARED_RUNTIME/certs/ca-certificates-2026.5.20.pem"

export MAMBA_ROOT_PREFIX="$HOME/micromamba"

"$MAMBA_EXE" config set ssl_verify "$SHARED_CA"
eval "$("$MAMBA_EXE" shell hook --shell zsh)"
```

micromamba 2.6系では、実行ファイルのbasenameが `micromamba` または `mamba` でなければ `run` や `activate` が正常に動作しない。また、symlinkは実体のversion付きファイル名へ解決されるため使用できない。共有directoryには `micromamba` という名前のbinaryコピーを用意する。

```bash
cd "$SHARED_RUNTIME/bin"
install -m 0755 micromamba-2.6.2 micromamba
```

各ユーザーは自分のhome directoryに環境とpackage cacheを持つ。必要であれば初期化部分を `~/.zshrc` に追加する。`micromamba info` の `envs directories` が自分のhome directory以下になっていることを確認する。

## 3. 環境作成

リポジトリへ移動し、CentOS 7サーバー用の直接依存versionを指定した環境を作成する。

```bash
cd "$HOME/thickness_measurement"

micromamba create \
  --file environment-server.yml

micromamba activate thickness-measurement
```

作成後の確認:

```bash
python --version
python -c 'import numpy, scipy, cv2, matplotlib; print(
    "numpy", numpy.__version__,
    "scipy", scipy.__version__,
    "opencv", cv2.__version__,
    "matplotlib", matplotlib.__version__
)'
root-config --version
root-config --cflags
cmake --version | head -n 1
c++ --version | head -n 1
```

## 4. Python版のテスト

```bash
cd "$HOME/thickness_measurement"
python -m pytest
```

## 5. C++/ROOT版のビルド

ROOT 6.40のconda-forge buildはC++20を使用する。プロジェクトのCMake設定は `ROOT_CXX_STANDARD` を読み、ROOTと同じC++標準を自動選択する。

```bash
cd "$HOME/thickness_measurement"

cmake -S . -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$CONDA_PREFIX"

cmake --build build
```

設定時に次のような表示が出ることを確認する。

```text
-- Using C++20 to match ROOT
```

## 6. 完全なlinux-64 lock fileの生成

最初の環境作成とテストが成功した後、間接依存を含むpackage URLを固定する。

```bash
micromamba env export \
  --name thickness-measurement \
  --explicit > environment-linux-64.lock
```

`environment-linux-64.lock` をリポジトリへcommitする。以降、同じサーバーの別ユーザーは次のコマンドで同一package集合を再現できる。

```bash
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
SHARED_RUNTIME=/shared/path/to/thickness-measurement/runtime
MAMBA_EXE="$SHARED_RUNTIME/bin/micromamba"
eval "$("$MAMBA_EXE" shell hook --shell zsh)"

cd "$HOME/thickness_measurement"
micromamba create \
  --name thickness-measurement \
  --file environment-linux-64.lock
```

## 7. 環境を有効化しない実行方法

batch処理やcronではshell初期化への依存を避けるため、`micromamba run` を利用できる。

```bash
micromamba run --name thickness-measurement \
  python track_thickness.py --help

micromamba run --name thickness-measurement \
  ./build/track_volume_root --help
```
