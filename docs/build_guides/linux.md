# Build AYON launcher on Linux

**WARNING:** Linux needs distribution specific steps.

We highly recommend to use prepared docker build options for Linux. If you want to build AYON on your local machine, the following steps may not be fully working for every case.

## Requirements
---

To build AYON you will need some tools and libraries. We do not provide any of these tools. You have to install them yourself.
- [**bash**](https://www.gnu.org/software/bash/)
- [**curl**](https://curl.se) on systems that doesn't have one preinstalled
- [**git**](https://git-scm.com/downloads)
- [**uv**](https://docs.astral.sh/uv/)
- [**Python 3.11**](https://www.python.org/downloads/) or higher
- [**CMake**](https://cmake.org/)

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
<summary>Use uv AYON build</summary>

You will need **bzip2**, **readline**, **sqlite3** and other libraries.

**For Ubuntu:**
```sh
sudo apt-get update; sudo apt-get install --no-install-recommends make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

**install uv**
```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```
</details>

## Build

#### Clone repository
```sh
git clone --recurse-submodules git@github.com:ynput/ayon-launcher.git
```

#### Prepare environment
Create virtual environment in `./.venv` and install python runtime dependencies like PySide, Pillow..

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
