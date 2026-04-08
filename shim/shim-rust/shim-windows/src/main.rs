#![cfg_attr(
    all(not(debug_assertions), target_os = "windows", feature = "gui"),
    windows_subsystem = "windows"
)]

use std::env;
use std::os::windows::process::CommandExt;
use std::process::{Command, Stdio};

const CREATE_NO_WINDOW: u32 = 0x08000000;

fn main() {
    let local_dir = match shim_core::get_launcher_local_dir() {
        Some(dir) => dir,
        None => {
            eprintln!("Failed to locate AYON local data directory.");
            std::process::exit(1);
        }
    };

    let mut final_path = match shim_core::find_latest_executable(&local_dir) {
        Ok(path) => path,
        Err(e) => {
            eprintln!("Shim was not able to locate any AYON launcher executables ({}).", e);
            std::process::exit(1);
        }
    };

    let is_ayon_console = cfg!(not(feature = "gui"));

    let args: Vec<String> = env::args().skip(1).collect();

    if let Some(parent) = final_path.parent() {
        if is_ayon_console {
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

    let mut command = Command::new(&final_path);
    command
        .args(&args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    if !is_ayon_console {
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.status() {
        Ok(s) => std::process::exit(s.code().unwrap_or(if s.success() { 0 } else { 1 })),
        Err(e) => {
            eprintln!("Failed to execute {}: {}", final_path.display(), e);
            std::process::exit(1);
        }
    }
}
