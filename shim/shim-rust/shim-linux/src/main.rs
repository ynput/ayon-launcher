use std::env;
use std::process::{Command, Stdio};

fn main() {
    let local_dir = match shim_core::get_launcher_local_dir() {
        Some(dir) => dir,
        None => {
            eprintln!("Failed to locate AYON local data directory.");
            std::process::exit(1);
        }
    };

    let final_path = match shim_core::find_latest_executable(&local_dir) {
        Ok(path) => path,
        Err(e) => {
            eprintln!("Shim was not able to locate any AYON launcher executables ({}).", e);
            std::process::exit(1);
        }
    };

    let args: Vec<String> = env::args().skip(1).collect();

    let mut command = Command::new(&final_path);
    command
        .args(&args)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    match command.status() {
        Ok(s) => std::process::exit(s.code().unwrap_or(if s.success() { 0 } else { 1 })),
        Err(e) => {
            eprintln!("Failed to execute {}: {}", final_path.display(), e);
            std::process::exit(1);
        }
    }
}
