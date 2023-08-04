
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

Building AYON Desktop application
------------

We aim to closely follow [**VFX Reference Platform**](https://vfxplatform.com/)

AYON is written in Python 3 with specific elements still running in Python2 until all DCCs are fully updated. To see the list of those, that are not quite there yet, go to [VFX Python3 tracker](https://vfxpy.com/)

[CX_Freeze](https://cx-freeze.readthedocs.io/en/latest) is used to freeze the Python code and all of its dependencies, and [Poetry](https://python-poetry.org/) for virtual environment management.

We provide comprehensive build steps:
* [Windows](docs/build_guides/windows.md)
* [macOS](docs/build_guides/macos.md)
* [Linux](docs/build_guides/linux.md) - needs distribution specific steps

Output of the build process is installer with metadata file that can be distributed to workstations.

Upload installer to server
----------------

Create installer information from json file on server and upload the installer file to be downloaded by users.

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
