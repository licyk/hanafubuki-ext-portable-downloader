# Portable package downloader for Hanafubuki

A [Hanafubuki](https://github.com/licyk/Hanafubuki) extension
(`io.github.licyk.portable-downloader`) that brings the
[sd-webui-all-in-one](https://github.com/licyk/sd-webui-all-in-one) portable
package downloader into the application: it lists the portable packages built
for your platform, downloads and extracts the one you choose, and registers it
as an instance you can open right away.

[中文说明](#中文说明)

## Features

- **Package list**: `portable_list.json`, fetched from its mirrors in order
  (licyk.github.io, GitHub, GitLab, Gitee) and cached, so the last list is
  shown offline. Only the packages for this platform are listed (Windows has
  most of them; Linux and macOS have ComfyUI).
- **Source and channel**: ModelScope or Hugging Face; nightly builds or stable
  releases, with a version picker per package.
- **GPU hint**: each package's GPU (NVIDIA, AMD, Intel, Apple Silicon, from its
  `_cuda`, `_rocm`, `_xpu`, `_mps` key) against a best-effort detection of the
  local GPUs. A package that suits this computer is listed first.
- **Download queue**: one download at a time, in order, as in the original
  downloader. Downloads use sd_webui_all_in_one's downloader (aria2 when it
  is installed, otherwise requests), resume after an interruption, and can be
  cancelled at any step. Progress shows on the page and in the Task Center.
- **Extract and register**: the archive is extracted with
  sd_webui_all_in_one's archive manager (7z through py7zr), or a `.7z` with
  7-Zip where py7zr is not installed (see [Requirements](#requirements)), into
  the folder you chose, optionally deleted, and the extracted package is
  registered with the application's discovery. **Open** takes you to the new
  instance.

## Requirements

Hanafubuki **0.3.29 or later, before 0.4** (`engines.hanafubuki`), with the
extension-validation host features:

- Python backends that import `sd_webui_all_in_one` (`[backend] sdWebuiAllInOne`);
- the `registerInstances` permission and the `instances.scan` host method;
- `host.info.instancesDir`;
- the `pages` slot for frames;
- the frame client's `pickDirectory()` and `navigateInstance()` (the page hides
  **Choose…** and **Open** when the host's client does not have them).

The backend's Python requirements are installed by the application into the
extension's data directory when it is turned on: `requests`, and on Windows
`py7zr` for the `.7z` packages. py7zr is not asked for on Python 3.15 (the
application's default), where its codecs publish no wheels and would need a
compiler. There a `.7z` package is extracted by 7-Zip's command line, as the
original downloader extracted it:

1. `7za`, `7z` or `7zz` on `PATH`, or `7z.exe` in 7-Zip's Program Files folder
   on Windows;
2. otherwise, on Windows (x64 and ARM64), the original downloader's standalone
   `7za.exe` (7-Zip 26.00), downloaded once from ModelScope
   (`licyks/sd-webui-all-in-one`, `7za/windows/<arch>/7za.exe`, at a pinned
   revision) into the data directory's `tools/`, and used only when its size
   and SHA-256 match and it runs;
3. on Linux and macOS there is no download: install 7-Zip (the `7zip` or
   `p7zip-full` package, or `brew install sevenzip`).

The tool is found before the package is downloaded. When neither py7zr nor
7-Zip can be had, a `.7z` package is refused with that reason unless extracting
after download is turned off, and is then left in the folder to extract by hand.
The Linux and macOS packages are `.tar.gz` and need neither.

## Install

- **From an archive**: Settings → Extensions → Install, and choose the
  `io.github.licyk.portable-downloader-<version>.zip` built by
  `scripts/package.py` (see [Packaging](#packaging)).
- **As a development link**: Settings → Extensions → Link a folder, and choose
  this repository's root (the package is the repository). The application
  reads the folder in place and refuses it if it holds any symbolic link, so
  `web/` installs its dependencies with npm and `bin-links=false`
  (`web/.npmrc`). Do not install them with bun or pnpm, which create links;
  `tests/test_package.py` checks for them. After changing the backend or the
  manifest, press **Reload** on the extension.

The install confirmation lists what it is granted: `instances = "read"` (to name
the instances a package became) and `registerInstances` (to register them).

## Usage

1. Open **Portable packages** in the application's navigation.
2. Pick the source and channel, search, and choose a version.
3. Check the download folder (by default the extension's setting, or the
   application's instances folder) or press **Choose…**. Each package goes into
   its own folder there.
4. Press **Download**. The queue shows each job's progress; **Cancel** stops
   it (a cancelled download resumes if you queue it again).
5. When it is done, press **Open** to go to the new instance.

Settings → Extensions → Portable package downloader holds the defaults: source,
channel, download tool, extract after download, delete the archive after
extracting, and the default folder.

## Development

```
backend/                 the backend (Python, run by the application on its managed Python)
  main.py                entry point; keeps file descriptor 1 for the protocol
  portable_downloader/   catalog, GPU, queue, pipeline, extraction child, 7-Zip, handler
schemas/settings.json    the Settings form
locales/                 the Settings strings (en, zh)
ui/                      the built page (committed)
web/                     the page's Vue 3 + Vite + TypeScript source
tests/                   the backend's and the package's tests
scripts/package.py       builds the installable archive
```

**The page** (`web/`, Node 22 or later):

```sh
cd web
npm install          # no bin links, see above
npm run check        # vue-tsc
npm test             # vitest
npm run build        # writes ../ui
```

The page runs in a sandboxed frame with an opaque origin and the policy
`script-src` its package only, `connect-src 'none'`: it has no inline script,
uses relative URLs, never fetches (everything goes through the frame client's
`call`, `state` and `onState`) and stores nothing. It takes its colours, type
and spacing from the theme tokens the host sends. The frame client is imported
as `@hanafubuki/frame`, which the build leaves external as
`../__hanafubuki/frame.js` (the host serves it at the package root).

**The backend's tests** need the Python SDK and sd_webui_all_in_one on the
import path, as the application provides them, and `requests` and `py7zr`:

```sh
export PYTHONPATH=/path/to/Hanafubuki/sdk/python:/path/to/sd-webui-all-in-one
python -m pytest
python -m ruff check . && python -m ruff format --check .
python -m ty check --python "$(command -v python)" backend tests
```

They read a recorded `portable_list.json`, serve mirrors and archives (zip,
tar.gz, 7z) from a local HTTP server, run whole jobs through the real
`download_file` and `extract_archive` against a stand-in host, and run
`backend/main.py` over the protocol. The 7-Zip fallback runs against a
stand-in script that speaks 7-Zip's command line and progress (POSIX only),
and against a real `7za`/`7z`/`7zz` when one is on `PATH`. `PORTABLE_DOWNLOADER_LIST_URLS`
(comma-separated) replaces the list's mirrors for the tests; the application
starts the backend in a clean environment, so it never reaches an installed
extension.

## Packaging

```sh
(cd web && npm run build)
python scripts/package.py            # dist/io.github.licyk.portable-downloader-<version>.zip
```

The archive holds the manifest, `backend/`, `schemas/`, `locales/`, `ui/`,
`requirements.txt` and this README, and none of `web/`, `tests/`, `scripts/`
or caches.

## 中文说明

整合包下载器是 Hanafubuki 的扩展：列出适用于当前平台的 sd-webui-all-in-one
整合包，下载并解压所选整合包，然后将其注册为实例，可直接打开。

- **功能**：从多个镜像获取并缓存整合包列表（离线时显示上次的列表）；可选
  ModelScope / Hugging Face 下载源和夜间构建版 / 稳定版；根据整合包标识提示显卡
  兼容性；按顺序逐个下载（aria2 或 requests，支持断点续传与取消）；使用
  sd_webui_all_in_one 解压，可选解压后删除压缩包；解压后通过应用的实例发现功能注册实例，
  并可一键打开。
- **7z 整合包**：py7zr 仅在 Windows 且 Python 低于 3.15 时安装。应用默认的 Python 3.15
  上改用 7-Zip 命令行解压：优先使用 `PATH` 中的 `7za`、`7z` 或 `7zz`（Windows 上还会查找
  Program Files 下的 `7-Zip\7z.exe`）；找不到时，Windows（x64 与 ARM64）会从 ModelScope
  （`licyks/sd-webui-all-in-one` 的 `7za/windows/<架构>/7za.exe`，固定版本）下载原下载器使用的
  `7za.exe`（7-Zip 26.00）到扩展数据目录的 `tools/` 中，仅下载一次，并校验大小、SHA-256
  且能正常运行后才使用；Linux 与 macOS 不会下载，请安装 7-Zip（`7zip` 或 `p7zip-full`
  软件包，或 `brew install sevenzip`）。Linux 与 macOS 的整合包为 `.tar.gz`，无需 7-Zip。
  py7zr 与 7-Zip 都不可用时，7z 整合包会在下载前被拒绝，需关闭“下载后解压”并手动解压。
- **要求**：Hanafubuki 0.3.29 及以上、0.4 以下，且包含扩展验证所需的宿主功能
  （`sdWebuiAllInOne`、`registerInstances` 与 `instances.scan`、
  `host.info.instancesDir`、`pages` 页面、frame 客户端的 `pickDirectory()` 与
  `navigateInstance()`）。
- **安装**：在 设置 → 扩展 中安装 `scripts/package.py` 生成的压缩包，或将本仓库根目录
  作为开发链接。开发链接的目录中不能有符号链接，因此 `web/` 须使用 npm 安装依赖
  （`web/.npmrc` 已设置 `bin-links=false`），不要使用 bun 或 pnpm。
- **使用**：在应用导航中打开“整合包下载”，选择下载源、版本通道和版本，确认下载目录后
  点击“下载”；完成后点击“打开”进入新实例。默认值可在 设置 → 扩展 中修改。
- **开发与打包**：见上文 [Development](#development) 与 [Packaging](#packaging)。
