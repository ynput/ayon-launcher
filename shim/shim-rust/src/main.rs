#![cfg_attr(
    all(not(debug_assertions), target_os = "windows", feature = "gui"),
    windows_subsystem = "windows"
)]

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use directories::ProjectDirs;
use serde::Deserialize;
use semver::Version;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Deserialize, Debug)]
struct VersionInfo {
    executable: String,
}

#[derive(Deserialize, Debug)]
struct ExecutablesInfo {
    // file_version: String,
    #[serde(default)]
    available_versions: Vec<VersionInfo>,
}

fn get_launcher_local_dir() -> Option<PathBuf> {
    if let Ok(storage_dir) = env::var("AYON_LAUNCHER_LOCAL_DIR") {
        return Some(PathBuf::from(storage_dir));
    }

    ProjectDirs::from("io", "Ynput", "AYON").map(|proj_dirs| {
        #[cfg(target_os = "windows")]
        return proj_dirs.data_local_dir().parent().unwrap().to_path_buf();
        #[cfg(not(target_os = "windows"))]
        proj_dirs.data_local_dir().to_path_buf()
    })
}

fn load_version_from_file(version_py: &Path) -> Option<String> {
    let content = match fs::read_to_string(version_py) {
        Ok(c) => c,
        Err(_) => {
            return None;
        }
    };
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

fn get_executable_version(executable_path: &Path) -> Option<String> {
    let parent = executable_path.parent()?;
    let version_py = parent.join("version.py");
    if version_py.exists() {
        return load_version_from_file(&version_py);
    }
    None
}

fn main() {
    let local_dir = match get_launcher_local_dir() {
        Some(dir) => dir,
        None => {
            eprintln!("Failed to locate AYON local data directory.");
            std::process::exit(1);
        }
    };

    let executables_json_path = local_dir.join("executables.json");
    if !executables_json_path.exists() {
        eprintln!("Shim was not able to locate any AYON launcher executables (missing executables.json at {}).", executables_json_path.display());
        std::process::exit(1);
    }

    let data = match fs::read_to_string(&executables_json_path) {
        Ok(content) => content,
        Err(e) => {
            eprintln!("Failed to read executables.json: {}", e);
            std::process::exit(1);
        }
    };

    let info: ExecutablesInfo = match serde_json::from_str(&data) {
        Ok(info) => info,
        Err(e) => {
            eprintln!("Failed to parse executables.json: {}", e);
            std::process::exit(1);
        }
    };

    let mut latest: Option<(Version, PathBuf)> = None;

    for version_info in info.available_versions {
        let path = PathBuf::from(&version_info.executable);
        if !path.exists() {
            continue;
        }

        if let Some(version_str) = get_executable_version(&path) {
            let version = Version::parse(&version_str).unwrap_or_else(|_| Version::new(0, 0, 0));
            
            if let Some((ref latest_v, _)) = latest {
                if version > *latest_v {
                    latest = Some((version, path));
                }
            } else {
                latest = Some((version, path));
            }
        }
    }

    let (_, mut final_path) = match latest {
        Some(pair) => pair,
        None => {
            eprintln!("Shim was not able to locate any valid AYON launcher executables.");
            std::process::exit(1);
        }
    };

    let args: Vec<String> = env::args().skip(1).collect();

    #[cfg(not(target_os = "macos"))]
    let use_open = false;
    // Determine if we should use 'open -na' on macOS
    #[cfg(target_os = "macos")]
    let use_open = {
        // If the target path looks like it's inside an .app bundle or is one
        let path_str = final_path.to_string_lossy();
        path_str.contains(".app") || path_str.ends_with(".app")
    };

    // Windows specific logic for ayon_console.exe
    // Determine if current shim is the console variant (Windows)
    #[cfg(target_os = "windows")]
    let is_ayon_console = {
        let exe_name = env::args().next().unwrap_or_default().to_lowercase();
        exe_name.contains("ayon_console")
    };
    // If running as console shim on Windows, prefer target's ayon_console.exe
    #[cfg(target_os = "windows")]
    {
        if is_ayon_console {
            if let Some(parent) = final_path.parent() {
                let console_exe = parent.join("ayon_console.exe");
                if console_exe.exists() {
                    final_path = console_exe;
                }
            }
        }
    }

    let mut command = if use_open {
        let mut cmd = Command::new("open");
        cmd.arg("-na").arg(&final_path);
        if !args.is_empty() {
            cmd.arg("--args").args(&args);
        }
        cmd
    } else {
        let mut cmd = Command::new(&final_path);
        cmd.args(&args);
        cmd
    };

    command
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    // Avoid spawning a new console window when the shim itself is a GUI app
    #[cfg(target_os = "windows")]
    {
        if !is_ayon_console {
            command.creation_flags(CREATE_NO_WINDOW);
        }
    }

    let status = command.status();
    match status {
        Ok(s) => {
            let code = s.code().unwrap_or(if s.success() { 0 } else { 1 });
            std::process::exit(code);
        }
        Err(e) => {
            eprintln!("Failed to execute {}: {}", final_path.display(), e);
            std::process::exit(1);
        }
    }
}
