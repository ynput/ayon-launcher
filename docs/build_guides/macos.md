# Build AYON launcher on macOS

**WARNING:** macOS is not fully supported. The build process may not work on some machines.

## Requirements
---

To build AYON you will need some tools and libraries. We do not provide any of these tools. You have to install them yourself.
- **Terminal**
- [**Homebrew**](https://brew.sh)
- [**git**](https://git-scm.com/downloads)
- [**Python 3.9**](https://www.python.org/downloads/) or higher
- [**CMake**](https://cmake.org/)
- **XCode Command Line Tools** (or some other build system).

Python 3.9.0 is not supported because of [this bug](https://github.com/python/cpython/pull/22670).

It is recommended to use [**pyenv**](https://github.com/pyenv/pyenv) for python version control.

### Prepare requirements
Easy way of installing everything necessary is to use [Homebrew](https://brew.sh).

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
   pyenv install 3.9.13
   ```

5) Set local Python version:
   ```sh
   # switch to AYON source directory
   pyenv local 3.9.13
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
