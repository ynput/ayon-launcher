#![cfg_attr(
    all(not(debug_assertions), target_os = "windows", feature = "gui"),
    windows_subsystem = "windows"
)]

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
#[cfg(target_os = "windows")]
use windows::Win32::UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK};
#[cfg(target_os = "windows")]
use windows::core::PCWSTR;
use directories::ProjectDirs;
use serde::Deserialize;
use semver::Version;

const CREATE_NO_WINDOW: u32 = 0x08000000;

#[cfg(not(target_os = "windows"))]
const IS_AYON_CONSOLE: bool = false;
#[cfg(target_os = "windows")]
const IS_AYON_CONSOLE: bool = cfg!(not(feature = "gui"));

fn show_error(msg: &str) {
    #[cfg(target_os = "windows")]
    {
        if !IS_AYON_CONSOLE {
            let wide: Vec<u16> = msg.encode_utf16().chain(std::iter::once(0)).collect();
            let title: Vec<u16> = "AYON Error\0".encode_utf16().collect();
            unsafe {
                MessageBoxW(None, PCWSTR(wide.as_ptr()), PCWSTR(title.as_ptr()), MB_OK | MB_ICONERROR);
            }
        }
    }

    #[cfg(target_os = "macos")]
    {
        let _ = Command::new("osascript")
            .arg("-e")
            .arg("display dialog (system attribute \"AYON_ERROR_MESSAGE\") with title \"AYON Error\" buttons {\"OK\"} default button \"OK\" with icon stop")
            .env("AYON_ERROR_MESSAGE", msg)
            .status();
    }

    // Not sure if we want to show error message on linux
    // #[cfg(target_os = "linux")]
    // {
    //     let has_display = env::var("DISPLAY").is_ok() || env::var("WAYLAND_DISPLAY").is_ok();
    //     if has_display {
    //         // Try zenity, then kdialog, then xmessage - use whichever is available.
    //         let shown = Command::new("zenity")
    //             .args(["--error", "--title=AYON Error", &format!("--text={}", msg)])
    //             .status()
    //             .is_ok();
    //         if !shown {
    //             let shown = Command::new("kdialog")
    //                 .args(["--error", msg, "--title", "AYON Error"])
    //                 .status()
    //                 .is_ok();
    //             if !shown {
    //                 let _ = Command::new("xmessage")
    //                     .args(["-center", msg])
    //                     .status();
    //             }
    //         }
    //     }
    // }
}


#[derive(Deserialize, Debug)]
pub struct VersionInfo {
    pub executable: String,
}

#[derive(Deserialize, Debug)]
pub struct ExecutablesInfo {
    #[serde(default)]
    pub available_versions: Vec<VersionInfo>,
}

pub fn get_launcher_local_dir() -> Option<PathBuf> {
    if let Ok(storage_dir) = env::var("AYON_LAUNCHER_LOCAL_DIR") {
        return Some(PathBuf::from(storage_dir));
    }


    #[cfg(target_os = "windows")]
    {
        return Some(ProjectDirs::from_path(PathBuf::from_iter(&["Ynput", "AYON"])).unwrap().data_local_dir().parent().unwrap().to_path_buf());
    }

    Some(ProjectDirs::from_path(PathBuf::from_iter(&["AYON"])).unwrap().data_local_dir().to_path_buf())
}

pub fn load_version_from_file(version_py: &Path) -> Option<String> {
    let content = fs::read_to_string(version_py).ok()?;
    for line in content.lines() {
        let line = line.trim().trim_start_matches('\u{feff}');
        if line.starts_with("__version__") {
            let parts: Vec<&str> = line.split('=').collect();
            if parts.len() == 2 {
                let version = parts[1].trim().trim_matches(|c| c == '"' || c == '\'');
                return Some(version.to_string());
            }
        }
    }
    None
}

pub fn get_executable_version(executable_path: &Path) -> Option<String> {
    let version_py = executable_path.parent()?.join("version.py");
    if version_py.exists() {
        return load_version_from_file(&version_py);
    }
    None
}

/// Reads `executables.json` from `local_dir`, compares semver of all listed
/// executables that actually exist on disk, and returns the path of the one
/// with the highest version.
pub fn find_latest_executable(local_dir: &Path) -> Result<PathBuf, String> {
    let executables_json_path = local_dir.join("executables.json");
    if !executables_json_path.exists() {
        return Err(format!(
            "missing executables.json at {}",
            executables_json_path.display()
        ));
    }

    let data = fs::read_to_string(&executables_json_path)
        .map_err(|e| format!("Failed to read executables.json: {}", e))?;

    let info: ExecutablesInfo = serde_json::from_str(&data)
        .map_err(|e| format!("Failed to parse executables.json: {}", e))?;

    let mut latest: Option<(Version, PathBuf)> = None;

    for version_info in info.available_versions {
        let path = PathBuf::from(&version_info.executable);
        if !path.exists() {
            continue;
        }
        if let Some(version_str) = get_executable_version(&path) {
            let version =
                Version::parse(&version_str).unwrap_or_else(|_| Version::new(0, 0, 0));
            match &latest {
                Some((latest_v, _)) if version <= *latest_v => {}
                _ => latest = Some((version, path)),
            }
        }
    }

    latest
        .map(|(_, path)| path)
        .ok_or_else(|| "No valid AYON launcher executables found".to_string())
}



fn main() {
    let local_dir = match get_launcher_local_dir() {
        Some(dir) => dir,
        None => {
            eprintln!("Failed to locate AYON local data directory.");
            show_error("Shim was not able to locate any AYON launcher executables.\n\nFailed to locate AYON local data directory.");
            std::process::exit(1);
        }
    };

    let mut final_path = match find_latest_executable(&local_dir) {
        Ok(path) => path,
        Err(e) => {
            eprintln!("Shim was not able to locate any AYON launcher executables ({}).", e);
            show_error("Shim was not able to locate any AYON launcher executables.");
            std::process::exit(1);
        }
    };

    let args: Vec<String> = env::args().skip(1).collect();

    #[cfg(target_os = "windows")]
    {
        if let Some(parent) = final_path.parent() {
            if IS_AYON_CONSOLE {
                let console_exe = parent.join("ayon_console.exe");
                if console_exe.exists() {
                    final_path = console_exe;
                }
            } else {
                let ui_exe = parent.join("ayon.exe");
                if ui_exe.exists() {
                    final_path = ui_exe;
                }
            }
        }
    }

    let mut command = Command::new(&final_path);
    command
        .args(&args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    #[cfg(target_os = "windows")]
    {
        if !IS_AYON_CONSOLE {
            command.creation_flags(CREATE_NO_WINDOW);
        }
    }

    match command.status() {
        Ok(s) => std::process::exit(s.code().unwrap_or(if s.success() { 0 } else { 1 })),
        Err(e) => {
            eprintln!("Failed to execute {}: {}", final_path.display(), e);
            show_error("Failed to start AYON launcher");
            std::process::exit(1);
        }
    }
}
