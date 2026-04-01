# AYON macOS Signing Configuration

This file documents the configuration needed for code signing and notarization of AYON launcher.

## Local Development Setup

For developers building locally on macOS, Signing requires:

1. **Apple Developer Account** with Developer ID certificate
2. **Signing Identity** (certificate name or hash)
3. **Optional: Keychain Profile** (for automated notarization)

### Example Local Configuration (bash)

> [!NOTE]
> AYON_APPLE_SIGN_IDENTITY: Using the certificate's hash instead of name is recommended.

```bash
# Set these environment variables before building:

# Required
export AYON_APPLE_CODESIGN="1"
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"


# Optional: Team ID (10-char value from Apple Developer portal)
export AYON_APPLE_TEAM_ID="XXXXXXXXXX"

# Optional: Path to entitlements file (defaults to tools/macos/ayon.entitlements)
export AYON_APPLE_ENTITLEMENTS="$(pwd)/tools/macos/ayon.entitlements"

# Optional: Enable notarization (requires below credentials)
export AYON_APPLE_NOTARIZE="1"
export AYON_APPLE_NOTARIZE_KEYCHAIN_PROFILE="ayon-notarize"  # See setup below

# Optional: Disable signing/notarization for non-release builds
# export AYON_APPLE_CODESIGN="0"

# Optional: Enable signing/notarization dry-run (prints commands, doesn't execute)
export AYON_APPLE_DRY_RUN="0"
```

### CI/CD Configuration (GitHub Actions)

Store these as GitHub repository secrets:

```bash
# Required for signing
APPLE_SIGN_IDENTITY         # Certificate name
APPLE_TEAM_ID              # 10-char Team ID from Apple

# Optional: For notarization via App Store Connect API
APPLE_NOTARIZE_KEY_ID      # NotaryAPI Key ID
APPLE_NOTARIZE_ISSUER_ID   # Issuer ID
APPLE_NOTARIZE_PRIVATE_KEY # Base64-encoded private key

# Alternative: Via Apple ID (not recommended for new setups)
APPLE_NOTARIZE_APPLE_ID    # Apple ID email address
APPLE_NOTARIZE_PASSWORD    # App-specific password
APPLE_NOTARIZE_TEAM_ID     # Team ID
```

### Setting Up Notarization Keychain Profile (One-time)

If using keychain profile (recommended for local development):

```bash
# Create a keychain profile for notarization
xcrun notarytool store-credentials ayon-notarize \
    --apple-id your-apple-id@example.com \
    --team-id XXXXXXXXXX \
    --password $(security find-generic-password -s "ayon-notarize" -w 2>/dev/null || echo "<paste_app_password>")

# Verify profile
xcrun notarytool history \
    --keychain-profile ayon-notarize
```

## Apple Developer Portal Prerequisites

### 1. Create App IDs

Navigate to **Certificates, Identifiers & Profiles** > **Identifiers**

Create two App IDs:
- **Main Launcher**: `com.ayon.launcher` (or your organization, e.g., `com.ynput.ayon`)
- **Shim**: `com.ayon.launcher.shim`

These should be Explicit identifiers (not wildcards), registered for **macOS** platform only.

### 2. Create Developer ID Certificates

Navigate to **Certificates, Identifiers & Profiles** > **Certificates**

Create or locate:
- **Certificate Type**: Developer ID Application
- **For**: Mac distribution outside the Mac App Store
- **CSR**: Generate one from Keychain Access on your Mac

### 3. Export Certificate for CI

On your local Mac:

```bash
# Export as .p12 file with password
open ~/Library/Keychains/login.keychain-db

# Or via command line:
security export -t certs -f pkcs12 -P <password> \
    ~/Library/Keychains/login.keychain-db \
    > ~/Developer_ID_Application.p12

# Base64-encode for GitHub Actions
base64 -i ~/Developer_ID_Application.p12 > ~/cert_base64.txt
# Store contents in APPLE_DEVELOPER_ID_CERTIFICATE (GitHub secret)
# Store password in APPLE_DEVELOPER_ID_PASSWORD
```

### 4. Register for Notarization

Notarization requires:

**Option A (Recommended): App Store Connect API**
- Requires **Account Holder** or **Admin** role in App Store Connect
- Create API key at https://appstore.connect.apple.com/access/api
- Note the **Key ID**, **Issuer ID**, and download **Private Key**

**Option B: Apple ID App-specific Password**
- Generate at https://appleid.apple.com/ > Security
- Less secure than API key; limit exposure to CI secrets

## Verifying Configuration

```bash
# Check certificate is installed and accessible
security find-identity -v -p codesigning

# Find your Developer ID Application certificate:
# (output shows identifier hash and certificate name)

# For keychain profile, verify notarization setup
xcrun notarytool history --keychain-profile ayon-notarize

# For Apple ID, test credentials
xcrun notarytool store-credentials --validate --keychain-profile ayon-test \
    --apple-id <apple-id> --team-id <team-id> --password <password>
```

## Build Commands

### Local Signing Only (No Notarization)

```bash
export AYON_APPLE_CODESIGN="1"
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"
./tools/make.sh build-make-installer
```

### Local with Notarization

```bash
export AYON_APPLE_CODESIGN="1"
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"
export AYON_APPLE_NOTARIZE="1"
export AYON_APPLE_NOTARIZE_KEYCHAIN_PROFILE="ayon-notarize"
./tools/make.sh build-make-installer
```

### Non-release CI Build (Skip Signing/Notarization)

```bash
export AYON_APPLE_CODESIGN="0"
export AYON_APPLE_NOTARIZE="0"
./tools/make.sh build-make-installer
```

### Dry-run (Print Commands Only)

```bash
export AYON_APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (XXXXXXXXXX)"
export AYON_APPLE_DRY_RUN="1"
./tools/make.sh build-make-installer
```

### Verify Existing DMG

```bash
# Check signature
codesign -v -v build/installer/AYON-*.dmg

# Check notarization staple
xcrun stapler validate build/installer/AYON-*.dmg

# Gatekeeper assessment
spctl --assess --verbose build/installer/AYON-*.dmg
```

## Troubleshooting

### "Codesign not found"
- Ensure Xcode command line tools are installed: `xcode-select --install`
- Or upgrade Xcode: `softwareupdate -l | grep -i xcode`

### "User is not authorized"
- Verify certificate is installed: `security find-identity -v -p codesigning`
- Check certificate hasn't expired or been revoked

### "Notarization rejected"
- Check notarytool history for details: `xcrun notarytool history --keychain-profile <profile>`
- Common issues: hardened runtime flags missing, invalid entitlements, or code not signed correctly
- Notarization is only attempted when `AYON_APPLE_CODESIGN=1` and `AYON_APPLE_NOTARIZE=1`

### "Staple failed"
- Notarization must succeed before stapling
- Run notarization again if unsure: `xcrun notarytool info <request-uuid> ...`

### Signing multiple binaries takes too long
- Signing order matters; nested binaries must be signed before top-level
- For development, consider code-signing only changed binaries (not automatic at this time)

## References

- [App Store Connect API Documentation](https://developer.apple.com/documentation/appstoreconnectapi)
- [Hardening Your Runtime](https://developer.apple.com/documentation/security/hardened_runtime)
- [Notarizing macOS Software Before Distribution](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
- [Developer ID Certificate Help](https://support.apple.com/en-us/HT208684)
