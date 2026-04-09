use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use directories::ProjectDirs;
use serde::Deserialize;
use semver::Version;

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
