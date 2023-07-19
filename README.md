
<!-- ALL-CONTRIBUTORS-BADGE:START - Do not remove or modify this section -->
[![All Contributors](https://img.shields.io/badge/all_contributors-28-orange.svg?style=flat-square)](#contributors-)
<!-- ALL-CONTRIBUTORS-BADGE:END -->
AYON Launcher - Desktop application
========

[![documentation](https://github.com/pypeclub/pype/actions/workflows/documentation.yml/badge.svg)](https://github.com/pypeclub/pype/actions/workflows/documentation.yml) ![GitHub VFX Platform](https://img.shields.io/badge/vfx%20platform-2022-lightgrey?labelColor=303846)


Introduction
------------

Desktop application launcher for AYON pipeline. You need AYON launcher to be able to interact with any of the integrated applications. it acts as the main entry point into the pipeline for all artists publishing and loading data with AYON. Even though AYON launcher is a standalone destkop application, it doesn't do anything until it's connected to an AYON server instance.

The documentation is not up-to-date as development is still in progress and code is changing every day.

To get all the information about the project, go to [AYON.io](https://ayon.ynput.io)

Requirements
------------

We aim to closely follow [**VFX Reference Platform**](https://vfxplatform.com/)

AYON is written in Python 3 with specific elements still running in Python2 until all DCCs are fully updated. To see the list of those, that are not quite there yet, go to [VFX Python3 tracker](https://vfxpy.com/)

The main things you will need to run and build AYON are:

- [**Python 3.9.6**](#python) or higher
- **Terminal** in your OS
    - PowerShell 5.0+ (Windows)
    - Bash (Linux)
- [**Inno Setup**](https://jrsoftware.org/isdl.php) for installer (Windows)

Building AYON Desktop application
-----------------

To build AYON you currently need [Python 3.9](https://www.python.org/downloads/) as we are following
[vfx platform](https://vfxplatform.com). Because of some Linux distros comes with newer Python version
already, you need to install **3.9** version and make use of it. You can use perhaps [pyenv](https://github.com/pyenv/pyenv) for this on Linux.
**Note**: We do not support 3.9.0 because of [this bug](https://github.com/python/cpython/pull/22670). Please, use higher versions of 3.9.x.

### Windows

You will need [Python >= 3.9.1](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads).
More tools might be needed for installing dependencies (for example for **OpenTimelineIO**) - mostly
development tools like [CMake](https://cmake.org/) and [Visual Studio](https://visualstudio.microsoft.com/cs/downloads/)

#### Clone repository:
```sh
git clone --recurse-submodules git@github.com:ynput/ayon-launcher.git
```

#### To build AYON Desktop:

1) Run `./tools/manage.ps1 create-env` to create virtual environment in `./.venv`.
2) Run `./tools/manage.ps1 install-runtime-dependencies` to install python runtime dependencies like PySide, Pillow.
3) Run `./tools/manage.ps1 build` to build AYON executables in `./build/output/`.
4) Run `./tools/manage.ps1 make-installer` to create an installer file in `./build/`.

AYON is build using [CX_Freeze](https://cx-freeze.readthedocs.io/en/latest) to freeze itself and all dependencies.

### macOS

**WARNING:** macOS is not fully supported. The build process may work on some machines. MacOS is also missing implementation of automated updates.

You will need [Python >= 3.9](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads). You'll need also other tools to build
some AYON dependencies like [CMake](https://cmake.org/) and **XCode Command Line Tools** (or some other build system).

Easy way of installing everything necessary is to use [Homebrew](https://brew.sh):

1) Install **Homebrew**:
   ```sh
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```

2) Install **cmake**:
   ```sh
   brew install cmake
   ```

3) Install [pyenv](https://github.com/pyenv/pyenv):
   ```sh
   brew install pyenv
   echo 'eval "$(pyenv init -)"' >> ~/.zshrc
   pyenv init
   exec "$SHELL"
   PATH=$(pyenv root)/shims:$PATH
   ```

4) Pull in required Python version 3.9.x:
   ```sh
   # install Python build dependences
   brew install openssl readline sqlite3 xz zlib

   # replace with up-to-date 3.9.x version
   pyenv install 3.9.6
   ```

5) Set local Python version:
   ```sh
   # switch to AYON source directory
   pyenv local 3.9.6
   ```

#### To build AYON:

1) Run `./tools/make.sh create-env` to create virtual environment in `./.venv`.
2) Run `./tools/make.sh install-runtime-dependencies` to install python runtime dependencies like PySide, Pillow.
3) Run `./tools/make.sh build` to build AYON executables in `./build/output/`.
4) Run `./tools/make.sh make-installer` to create an installer file in `./build/`.

### Linux

#### Manual build
You will need [Python >= 3.9](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads). You'll also need [curl](https://curl.se) on systems that doesn't have one preinstalled.

To build Python related stuff, you need Python header files installed (`python3-dev` on Ubuntu for example).

You'll need also other tools to build
some AYON dependencies like [CMake](https://cmake.org/). Python 3 should be part of all modern distributions. You can use your package manager to install **git** and **cmake**.

<details>
<summary>Details for Ubuntu</summary>
Install git, cmake and curl

```sh
sudo apt install build-essential checkinstall
sudo apt install git cmake curl
```
#### Note:
In case you run in error about `xcb` when running AYON,
you'll need also additional libraries for Qt5:

```sh
sudo apt install qt5-default
```
or if you are on Ubuntu > 20.04, there is no `qt5-default` packages so you need to install its content individually:

```sh
sudo apt-get install qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools
```
</details>

<details>
<summary>Details for Centos</summary>
Install git, cmake and curl

```sh
sudo yum install qit cmake
```

#### Note:
In case you run in error about `xcb` when running AYON,
you'll need also additional libraries for Qt5:

```sh
sudo yum install qt5-qtbase-devel
```
</details>

<details>
<summary>Use pyenv to install Python version for AYON build</summary>

You will need **bzip2**, **readline**, **sqlite3** and other libraries.

For more details about Python build environments see:

https://github.com/pyenv/pyenv/wiki#suggested-build-environment

**For Ubuntu:**
```sh
sudo apt-get update; sudo apt-get install --no-install-recommends make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

**For Centos:**
```sh
yum install gcc zlib-devel bzip2 bzip2-devel readline-devel sqlite sqlite-devel openssl-devel tk-devel libffi-devel
```

**install pyenv**
```sh
curl https://pyenv.run | bash

# you can add those to ~/.bashrc
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"

# reload shell
exec $SHELL

# install Python 3.9.x
pyenv install -v 3.9.6

# change path to repository
cd /path/to/OpenPype

# set local python version
pyenv local 3.9.6

```
</details>

#### To build AYON:

1) Run `./tools/make.sh create-env` to create virtual environment in `./.venv`.
2) Run `./tools/make.sh install-runtime-dependencies` to install python runtime dependencies like PySide, Pillow.
3) Run `./tools/make.sh build` to build AYON executables in `./build/output/`.
4) Run `./tools/make.sh make-installer` to create an installer file in `./build/`.


Upload installer to server
----------------

Installer must be available on a server to be able to set it in release bundle and to be downloaded by users.

### Windows
Run `./tools/manage.ps1 upload --server <your server> --api-key <your api key>`

### Linux & macOS
Run `./tools/make.sh upload --server <your server> --api-key <your api key>`

Upload command has more options, run `./tools/manage.ps1 upload --help` or `./tools/make.sh upload --help` to see them. For example, it is posssible to use username & password instead of api key.


Running AYON Desktop application
----------------

AYON can be executed either from live sources (this repository) or from
*"frozen code"* - executables that can be build using steps described above.

### From sources
AYON can be run directly from sources by activating virtual environment:

```sh
poetry run python start.py &args
```

### From frozen code

You need to build AYON first. This will produce executable - `ayon.exe` and `ayon_console.exe` on Windows, `ayon` on Linux and `AYON {version}.app` for macOS.

#### Windows
Executable `ayon_console.exe` creates console with output - useful for debugging, `ayon.exe` does not create console, but does not have any stdout or stderr output.
