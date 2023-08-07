# Build AYON launcher on Windows

## Requirements
---

To build AYON you will need some tools and libraries. We do not provide any of these tools. You have to install them yourself.
- **PowerShell** 5.0+ [GitHub repository](https://github.com/PowerShell/PowerShell)
- [**git**](https://git-scm.com/downloads)
- [**Python 3.9**](https://www.python.org/downloads/) or higher
- [**Inno Setup**](https://jrsoftware.org/isdl.php) for installer

Python 3.9.0 is not supported because of [this bug](https://github.com/python/cpython/pull/22670).

It is recommended to use [**pyenv**](https://github.com/pyenv/pyenv) for python version control.

### More tools **might** be needed for installing python dependencies
- [**CMake**](https://cmake.org/)
- [**Visual Studio**](https://visualstudio.microsoft.com/cs/downloads/)

## Build

Open PowerShell and change directory where you want to clone repository.
#### Clone repository
```sh
git clone --recurse-submodules git@github.com:ynput/ayon-launcher.git
```

#### Prepare environment
Create virtual environment in `./.venv` and install python runtime dependencies like PySide, Pillow..
```
./tools/manage.ps1 create-env
./tools/manage.ps1 install-runtime-dependencies
```

#### Build AYON Desktop
Build AYON executables in `./build/output/`.
```
./tools/manage.ps1 build
```

#### Create installer
Create installer that can be distributed to server and workstations.
```
./tools/manage.ps1 make-installer
```

Output files are in `./build/installer/` directory. You should find `.exe` and `.json` file. JSON file contains metadata required for server.
