AYON Launcher - Desktop application
========

![GitHub VFX Platform](https://img.shields.io/badge/vfx%20platform-2022-lightgrey?labelColor=303846)


Introduction
------------

Desktop application launcher for AYON pipeline. You need AYON launcher to be able to interact with any of the integrated applications. It acts as the main entry point into the pipeline for all artists publishing and loading data with AYON. Even though AYON launcher is a standalone desktop application, it doesn't do anything until it's connected to an AYON server instance.

The main purpose of application is to distribute updates based on current server state and to start main logic of core addon. At this moment core addon is `ayon_core`.

Desktop application also deploys AYON shim, which acts as bridge for different versions of AYON launcher. More information [here](#shim).

To get all the information about the project, go to [AYON.io](https://ayon.ynput.io)

Shim
------------

AYON shim is a small executable that knows where to find "real" executable of AYON launcher.

Usage of shim:
1. Handle custom uri protocol scheme `ayon-launcher://` which is used for running web actions.
2. Path to shim executable can be used for shortcuts and automations, so you don't need to worry about updating the path on AYON launcher update. This might be useful e.g. for Deadline plugin.

Shim is installed with AYON launcher, or on first run of AYON launcher. It is installed to app data which is based on OS, or to `{AYON_LAUNCHER_LOCAL_DIR}/shim/` directory if `AYON_LAUNCHER_LOCAL_DIR` environment variable is set.

Windows installation requires admin privileges, you'll be prompted for them on installation of AYON launcher.

<details>

<summary>Windows registry</summary>

You can register custom uri protocol scheme `ayon-launcher://` by adding following registry keys:
It uses default shim executable path `%LOCALAPPDATA%\Ynput\AYON\shim\ayon.exe`.

```
Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\ayon-launcher]
"URL Protocol"=""

[HKEY_CLASSES_ROOT\ayon-launcher\DefaultIcon]
@=hex(2):25,00,4c,00,4f,00,43,00,41,00,4c,00,41,00,50,00,50,00,44,00,41,00,54,\
  00,41,00,25,00,5c,00,59,00,6e,00,70,00,75,00,74,00,5c,00,41,00,59,00,4f,00,\
  4e,00,5c,00,73,00,68,00,69,00,6d,00,5c,00,61,00,79,00,6f,00,6e,00,2e,00,65,\
  00,78,00,65,00,00,00

[HKEY_CLASSES_ROOT\ayon-launcher\shell]

[HKEY_CLASSES_ROOT\ayon-launcher\shell\open]

[HKEY_CLASSES_ROOT\ayon-launcher\shell\open\command]
@=hex(2):25,00,4c,00,4f,00,43,00,41,00,4c,00,41,00,50,00,50,00,44,00,41,00,54,\
  00,41,00,25,00,5c,00,59,00,6e,00,70,00,75,00,74,00,5c,00,41,00,59,00,4f,00,\
  4e,00,5c,00,73,00,68,00,69,00,6d,00,5c,00,61,00,79,00,6f,00,6e,00,2e,00,65,\
  00,78,00,65,00,20,00,22,00,25,00,31,00,22,00,00,00

```

</details>

> [!CAUTION]
> Shim on macOs is installed to `/Applications/AYON.app`. To be able to use it in automation which waits for AYON launcher to finish then you have to use full path to executable `/Applications/AYON.app/Contents/MacOS/ayon`.

Building AYON Desktop application
------------

We aim to closely follow [**VFX Reference Platform**](https://vfxplatform.com/)

AYON is written in Python 3 with specific elements still running in Python2 until all DCCs are fully updated. To see the list of those, that are not quite there yet, go to [VFX Python3 tracker](https://vfxpy.com/)

[CX_Freeze](https://cx-freeze.readthedocs.io/en/latest) is used to freeze the Python code and all of its dependencies, and [Poetry](https://python-poetry.org/) for virtual environment management.

We provide comprehensive build steps:
* [Windows](docs/build_guides/windows.md)
* [macOS](docs/build_guides/macos.md)
* [Linux](docs/build_guides/linux.md) - needs distribution specific steps

### Linux build
We do recommend to use docker build options for linux distributions. Prepared dockerfiles do all necessary steps for you.

**NOTE:** There might be cases when linux installer should use PySide2 instead of PySide6 (which is default). You can change this by using `--use-pyside2` in docker build command. Or you can use env variable `QT_BINDING=pyside2` for local build.
We do handle that case for Centos 7 build, but all other variants are using PySide6 by default.

Output of the build process is installer with metadata file that can be distributed to workstations.

Upload installer to server
----------------

Create installer information from json file on server and upload the installer file to be downloaded by users.

### Windows
Run `./tools/manage.ps1 upload --server <your server> --api-key <your api key>`

*Or,* run `./tools/manage.ps1 upload --server <your server> --username <your admin username> --password  <your pasword>`

### Linux & macOS
Run `./tools/make.sh upload --server <your server> --api-key <your api key>`

*Or,* run `./tools/make.sh upload --server <your server> --username <your admin username> --password  <your pasword>`


Upload command has more options, use `--help` to investigate them. For example, it is possible to use username & password instead of api key.


Running AYON Desktop application
----------------

AYON can be executed either from live sources (this repository) or from
*"frozen code"* - executables that can be build using steps described above.

### From sources
You need to create env and install dependencies first.
> Ideally, this step should be re-run with each new version.

#### Windows
```
./tools/manage.ps1 create-env
./tools/manage.ps1 install-runtime-dependencies
```

#### Linux & macOS
```
./tools/make.sh create-env
./tools/make.sh install-runtime-dependencies
```
### Run
AYON can be run directly from sources by activating virtual environment:

#### Windows
```
./tools/manage.ps1 run
```

#### Linux & macOS
```
./tools/make.sh run
```
### From frozen code

You need to build AYON first. This will produce executable - `ayon.exe` and `ayon_console.exe` on Windows, `ayon` on Linux and `AYON {version}.app` for macOS.

#### Windows
Executable `ayon_console.exe` creates console with output - useful for debugging, `ayon.exe` does not create console, but does not have any stdout or stderr output.


Startup
-------------
Once AYON launcher is installed and launched there are few ways how to affect what will happen. Default behavior will ask for login to server, if user did not log in yet, then starts distribution of updates, and last step is to start the main logic.

Main logic is now using command line handling from `ayon_core` addon. If path to python script is passed it will start the python script as main logic instead.

### Arguments
There are reserver global arguments that cannot be used in any cli handling:
- `init-ayon-launcher` - Initialize launcher. Register executable path to known AYON launcher locations, and install shim executable.
- `--bundle <BUNDLE NAME>` - Force AYON to use specific bundle instead of the one that is set in the config file. This is useful for testing new bundles before they are released.
- `--verbose <LOG LEVEL>` - Change logging level to one of the following: DEBUG, INFO, WARNING, ERROR, CRITICAL.
- `--debug` - Simplified way how to change verbose to DEBUG. Also sets `AYON_DEBUG` environment variable to `1`.
- `--skip-headers` - Skip headers in the console output.
- `--use-dev` - Use dev bundle and settings, if bundle is not explicitly defined.
- `--use-staging` - Use staging settings, and use staging bundle, if bundle is not explicitly defined. Cannot be combined with staging.
- `--headless` - Tell AYON to run in headless mode. No UIs are shown during bootstrap. Affects `AYON_HEADLESS_MODE` environment variable. Custom logic must handle headless mode on own.
- `--ayon-login` - Show login dialog on startup.
- `--skip-bootstrap` - Skip bootstrap process. Used for inner logic of distribution.

### Environment variables
Environment variables that are set during startup:
- **AYON_VERSION** - Version of AYON launcher.
- **AYON_BUNDLE_NAME** - Name of bundle that is used.
- **AYON_LOG_LEVEL** - Log level that is used.
- **AYON_DEBUG** - Debug flag enabled when set to '1'.
- **AYON_USE_STAGING** - Use staging settings when set to '1'.
- **AYON_USE_DEV** - Use dev mode settings when set to '1'.
- **AYON_HEADLESS_MODE** - Headless mode flag enabled when set to '1'.
- **AYON_EXECUTABLE** - Path to executable that is used to run AYON.
- **AYON_ROOT** - Root to AYON launcher content.
- **AYON_LAUNCHER_STORAGE_DIR** - Directory where are stored dependency packages, addons and files related to addons. At own risk can be shared (NOT TESTED).
- **AYON_LAUNCHER_LOCAL_DIR** - Directory where are stored user/machine specific files. This MUST NOT be shared.
- **AYON_ADDONS_DIR** - Path to AYON addons directory - Still used but considered as deprecated. Please rather use 'AYON_LAUNCHER_STORAGE_DIR' to change location.
- **AYON_DEPENDENCIES_DIR** - Path to AYON dependencies directory - Still used but considered as deprecated. Please rather use 'AYON_LAUNCHER_STORAGE_DIR' to change location.

> [!NOTE]
> Environment variables **AYON_LAUNCHER_STORAGE_DIR** and **AYON_LAUNCHER_LOCAL_DIR** are by default set to the same folder. Path is based on OS.
> - Windows: `%LOCALAPPDATA%\Ynput\AYON`
> - Linux: `~/.local/share/AYON`
> - macOS: `~/Library/Application Support/AYON`
> It is required to set the environment variables before AYON launcher is started as it is required for bootstrap.

> [!TIP]
> Environment variables **AYON_ADDONS_DIR** and **AYON_DEPENDENCIES_DIR** by default lead relative to **AYON_LAUNCHER_STORAGE_DIR**.
> - **AYON_ADDONS_DIR** -> `{AYON_LAUNCHER_STORAGE_DIR}/addons`
> - **AYON_DEPENDENCIES_DIR** -> `{AYON_LAUNCHER_STORAGE_DIR}/dependency_packages`
> Changing their values will change where addons and dependency packages are stored even if you change **AYON_LAUNCHER_STORAGE_DIR**!

- **AYON_MENU_LABEL** - Label for AYON menu -> TODO move to ayon_core addon.

- **SSL_CERT_FILE** - Use certificates from 'certifi' if 'SSL_CERT_FILE' is not set.

## Developer mode
Developer mode enables to skip standard distribution process and use local sources of addon code. This is useful for development of addon. Developer mode must be enabled and configured on AYON server. To use it in AYON launcher create dev bundle and use `--use-dev` argument, or define bundle name `--bundle <dev bundle name>` in cli arguments.

## Links
- [Launcher Dev | AYON Docs](https://ayon.ynput.io/docs/dev_launcher)
- [AYON Developer Mode – Guide | AYON Forums](https://community.ynput.io/t/ayon-developer-mode-guide/993)
- [How to keep up with AYON updates? | AYON Forums](https://community.ynput.io/t/how-to-keep-up-with-ayon-updates/1066)


## TODOs
- [ ] Use 'platformdirs' instead of 'appdirs'.
- [ ] Remove unused 'acre' dependency. Now has to be kept for ayon-core compatibility.
