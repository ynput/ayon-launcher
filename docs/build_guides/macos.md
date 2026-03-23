# Build AYON launcher on macOS

> [!WARNING]
> macOS is not fully supported. The build process may not work on some machines.
> We try to upload pre-build installer in each release.

## Requirements
---
> [!IMPORTANT]
> If you're on M1 or newer mac, you also have to enable Rosetta virtualization on Terminal application. That has to be done before you start the build process or install dependencies. You might have to reinstall dependencies if you've already had installed them.

To build AYON you will need some tools and libraries. We do not provide any of these tools. You have to install them yourself.
- **Terminal**
- [**Homebrew**](https://brew.sh)
- [**git**](https://git-scm.com/downloads)
- [**uv**](https://docs.astral.sh/uv/)
- [**Python 3.11**](https://www.python.org/downloads/)
- [**CMake**](https://cmake.org/)
- **XCode Command Line Tools** (or some other build system).

### Prepare requirements
Easy way of installing everything necessary is to use [Homebrew](https://brew.sh).

1) Install **Homebrew**:
   ```sh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2) Install **cmake** and **create-dmg**:
   ```sh
   brew install cmake create-dmg
   ```

3) Install [uv](https://docs.astral.sh/uv/getting-started/installation/):
   ```sh
   brew install uv
   ```

4) Pull in required Python version 3.11.x:
   ```sh
   # install Python build dependences
   brew install openssl readline sqlite3 xz zlib

   # replace with up-to-date 3.11.x version
   uv python install 3.11.9
   ```

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
