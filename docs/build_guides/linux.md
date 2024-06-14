# Build AYON launcher on Linux

**WARNING:** Linux needs distribution specific steps.

## Requirements
---

To build AYON you will need some tools and libraries. We do not provide any of these tools. You have to install them yourself.
- [**bash**](https://www.gnu.org/software/bash/)
- [**curl**](https://curl.se) on systems that doesn't have one preinstalled
- [**git**](https://git-scm.com/downloads)
- [**Python 3.9**](https://www.python.org/downloads/) or higher
- [**CMake**](https://cmake.org/)

Python 3.9.0 is not supported because of [this bug](https://github.com/python/cpython/pull/22670).

It is recommended to use [**pyenv**](https://github.com/pyenv/pyenv) for python version control.

To build Python related stuff, you need Python header files installed (`python3-dev` on Ubuntu for example).

### Prepare requirements
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
sudo apt install qt6-default
```
or if you are on Ubuntu > 20.04, there is no `qt6-default` packages so you need to install its content individually:

```sh
sudo apt-get install qtbase6-dev qtchooser qt6-qmake qtbase6-dev-tools
```
</details>

<details>
<summary>Details for Centos 7</summary>
Note that centos 7 is old OS and some of the packages are not available so there might be used older versions. For example still uses PySide2 instead of PySide6.
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

## Build

#### Clone repository
```sh
git clone --recurse-submodules git@github.com:ynput/ayon-launcher.git
```

#### Prepare environment
Create virtual environment in `./.venv` and install python runtime dependencies like PySide, Pillow..

**For Centos:**
Centos does not support default version of PySide6. We've prepared last supported version, all you need to do is to set environment variable `QT_BINDING` to `centos7`.

```
./tools/make.sh create-env
./tools/make.sh install-runtime-dependencies
```

#### Build AYON Desktop
Build AYON in `./build/`.
```
./tools/make.sh build
```

Build should create `./build/AYON {version}.app` file.

#### Create installer
Create installer that can be distributed to server and workstations.
```
./tools/make.sh make-installer
```

Output installer is in `./build/installer/` directory. You should find `.dmg` and `.json` file. JSON file contains metadata required for server.
