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
- [**Python 3.9**](https://www.python.org/downloads/) or higher
- [**CMake**](https://cmake.org/)
- **XCode Command Line Tools** (or some other build system).

Python 3.9.0 is not supported because of [this bug](https://github.com/python/cpython/pull/22670).

> [!TIP]
> It is recommended to use [**pyenv**](https://github.com/pyenv/pyenv) for python version control.

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

## Code Signing and Notarization (for Distribution)

For distributing AYON outside the Mac App Store (as a standalone application), code signing and notarization are **required** for modern macOS security policies.

### Prerequisites

1. **Apple Developer Account** - Register at [developer.apple.com](https://developer.apple.com)
2. **Developer ID Certificate** - Obtained from [Apple Developer portal](https://developer.apple.com/account/resources/certificates/)
3. **Team ID** - Your 10-character team identifier (found in Apple Developer portal)

### Configuration

See [tools/macos/SIGNING_CONFIG.md](../../tools/macos/SIGNING_CONFIG.md) for detailed setup instructions, including:

- Creating Apple Developer certificates
- Setting up notarization credentials
- Configuring environment variables
- Troubleshooting common issues

### Building with Code Signing

#### Local signing only

```sh
export AYON_APPLE_CODESIGN="1"
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"
./tools/make.sh build-make-installer
```

> [!NOTE]
> Using the certificate's hash instead of name is recommended for CI environments

#### With full notarization workflow

```sh
export AYON_APPLE_CODESIGN="1"
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"
export AYON_APPLE_TEAM_ID="XXXXXXXXXX"
export AYON_APPLE_NOTARIZE="1"
export AYON_APPLE_NOTARIZE_KEYCHAIN_PROFILE="ayon-notarize"
./tools/make.sh build-make-installer
```
> [!NOTE]
> Using the certificate's hash instead of name is recommended for CI environments

#### Skip signing and notarization (non-release CI)

```sh
export AYON_APPLE_CODESIGN="0"
export AYON_APPLE_NOTARIZE="0"
./tools/make.sh build-make-installer
```

#### Dry-run mode

```sh
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"
export AYON_APPLE_DRY_RUN="1"
./tools/make.sh build-make-installer
```

### Verifying Signed DMG

After building, verify the code signatures and notarization:

```sh
# Check app bundle signature
codesign -v -v build/AYON\ *.app

# Check DMG signature (if notarized and stapled)
xcrun stapler validate build/installer/AYON-*.dmg

# Run Gatekeeper assessment
spctl --assess --verbose build/installer/AYON-*.dmg
```

### Environment Variables Reference

| Variable | Required | Description |
| --- | --- | --- |
| `AYON_APPLE_CODESIGN` | No | Set to `1` to enable code signing (default), or `0` to skip signing entirely |
| `AYON_APPLE_SIGN_IDENTITY` | Yes (for signing) | Certificate identity (name or hash) |
| `AYON_APPLE_TEAM_ID` | No | Team ID for hardened runtime (10 chars) |
| `AYON_APPLE_ENTITLEMENTS` | No | Path to entitlements file (defaults to `tools/macos/ayon.entitlements`) |
| `AYON_APPLE_NOTARIZE` | No | Set to `1` to enable notarization submission (only applied when `AYON_APPLE_CODESIGN=1`) |
| `AYON_APPLE_NOTARIZE_KEYCHAIN_PROFILE` | No (if using Apple ID) | Keychain profile name for notarization |
| `AYON_APPLE_NOTARIZE_APPLE_ID` | No (if using profile) | Apple ID email for notarization |
| `AYON_APPLE_NOTARIZE_PASSWORD` | No (if using profile) | Apple ID app-specific password |
| `AYON_APPLE_NOTARIZE_TEAM_ID` | No (if using profile) | Team ID for notarization auth |
| `AYON_APPLE_BUNDLE_ID` | No | Main app bundle ID (defaults to `com.ayon.launcher`) |
| `AYON_APPLE_SHIM_BUNDLE_ID` | No | Shim app bundle ID (defaults to `com.ayon.launcher.shim`) |
| `AYON_APPLE_DRY_RUN` | No | Set to `1` for dry-run (print commands) |
| `AYON_APPLE_VERBOSE` | No | Set to `1` for verbose logging |

### Signing Architecture

The AYON launcher uses **deterministic multi-stage code signing** to ensure valid signatures for all nested content:

**Pre-step: Strip Extended Attributes**
- Removes resource forks, Finder info, quarantine flags, and other extended attributes
- macOS `codesign` refuses to seal bundles containing these

**Step 0: Strip Spurious +x Bits**
- Removes executable permission from files that are not Mach-O binaries
- Prevents signing errors on non-code files with stray executable bits

**Step 1: Relocate Non-Code to Resources**
- Moves Python scripts, configs, and data files from `Contents/MacOS/` to `Contents/Resources/`
- Creates relative symlinks in `MacOS/` to preserve runtime path resolution
- macOS `codesign` treats everything under `MacOS/` as code that must be individually signed

**Step 2: Sign Nested Bundles (Deepest-First)**
- Discovers all `.app` and `.framework` bundles in the tree
- Signs them inside-out: deepest bundles first, same-depth in parallel
- Each bundle: sign loose Mach-O files, then seal the bundle itself

**Step 3: Sign Loose Mach-O Binaries**
- Signs remaining executable files at the top level
- Excludes the main `CFBundleExecutable` (signed during bundle sealing)

**Step 4: Seal Top-Level App Bundle**
- Signs the main executable and seals the entire `.app` bundle
- Applies entitlements and hardened runtime flags

This inside-out ordering ensures child bundles are valid before their parents, meeting Apple's hardened runtime requirements.

### Entitlements

Two entitlements files are provided:

- **`tools/macos/ayon.entitlements`** - Main launcher (full capabilities)
- **`tools/macos/ayon_helper.entitlements`** - Helper executables (restricted)

These enable:

- Python JIT compilation (required for Python runtime)
- Unsigned executable memory loading
- Dynamic library loading for Python extensions
- Network client/server connections
- File access via user dialogs
- Keychain access for credential storage

### Notarization Workflow

When both `AYON_APPLE_CODESIGN=1` and `AYON_APPLE_NOTARIZE=1` are set:

1. After DMG creation, the installer is submitted to Apple's notarization service
2. Notarization status is polled (typically 2-10 minutes)
3. If successful, the notarization ticket is stapled to the DMG
4. Stapling embeds the ticket, allowing offline verification

### Troubleshooting

**Signature verification fails:**

```sh
# Re-verify with verbose output
codesign -d -vv build/AYON\ *.app
```

**Notarization rejected:**

```sh
# Check detailed rejection reason
xcrun notarytool history --keychain-profile <profile>
```

**"Codesign not found":**

```sh
# Install Xcode command-line tools
xcode-select --install
```

For more troubleshooting, see [tools/macos/SIGNING_CONFIG.md](../../tools/macos/SIGNING_CONFIG.md).

### CI/CD Integration

For automated building and signing in CI/CD pipelines (e.g., GitHub Actions):

1. Store certificate as base64-encoded GitHub secret: `APPLE_DEVELOPER_ID_CERTIFICATE`
2. Store certificate password as secret: `APPLE_DEVELOPER_ID_PASSWORD`
3. Store notarization credentials as secrets (app-specific password or API key)
4. Configure workflow to export certificate and set environment variables
5. Run `./tools/make.sh build-make-installer`

Example GitHub Actions snippet:

```yaml
- name: Import Code Signing Certificate
  uses: apple-actions/import-codesign-certs@v2
  with:
    p12-file-base64: ${{ secrets.APPLE_DEVELOPER_ID_CERTIFICATE }}
    p12-password: ${{ secrets.APPLE_DEVELOPER_ID_PASSWORD }}

- name: Build and Sign AYON
  env:
    AYON_APPLE_CODESIGN: '1'
    AYON_APPLE_SIGN_IDENTITY: ${{ secrets.APPLE_SIGN_IDENTITY }}
    AYON_APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
    AYON_APPLE_NOTARIZE: '1'
    AYON_APPLE_NOTARIZE_KEYCHAIN_PROFILE: ayon-notarize-ci
  run: ./tools/make.sh build-make-installer
```

For non-release CI builds, set `AYON_APPLE_CODESIGN: '0'` and `AYON_APPLE_NOTARIZE: '0'`.
