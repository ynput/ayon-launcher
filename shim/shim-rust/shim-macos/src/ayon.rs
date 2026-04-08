use std::env;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use objc::runtime::Object;
use objc::{msg_send, sel, sel_impl};
use block::ConcreteBlock;

mod macos_events {
    use super::*;

    pub fn setup_apple_event_handlers() -> Arc<Mutex<Vec<String>>> {
        let captured_args = Arc::new(Mutex::new(Vec::new()));

        unsafe {
            let ns_app: *mut Object = msg_send![objc::class!(NSApplication), sharedApplication];
            if ns_app.is_null() {
                return captured_args;
            }

            // Accessory policy: no Dock icon but can receive Apple events.
            let _: () = msg_send![ns_app, setActivationPolicy: 1isize];
            let _: () = msg_send![ns_app, finishLaunching];

            let event_manager: *mut Object =
                msg_send![objc::class!(NSAppleEventManager), sharedAppleEventManager];
            if event_manager.is_null() {
                return captured_args;
            }

            // kAEOpenApplication
            let open_app_block =
                ConcreteBlock::new(move |_event: *mut Object, _reply: *mut Object| {});
            let open_app_handler = open_app_block.copy();

            // kAEOpenDocuments
            let clone = Arc::clone(&captured_args);
            let open_file_block =
                ConcreteBlock::new(move |event: *mut Object, _reply: *mut Object| {
                    let list: *mut Object =
                        msg_send![event, paramDescriptorForKeyword: 0x2d2d2d2du32];
                    let count: isize = msg_send![list, numberOfItems];
                    let mut args = clone.lock().unwrap();
                    for i in 1..=count {
                        let desc: *mut Object = msg_send![list, descriptorAtIndex: i];
                        let ns_str: *mut Object = msg_send![desc, stringValue];
                        if ns_str.is_null() {
                            continue;
                        }
                        let c_str: *const std::os::raw::c_char =
                            msg_send![ns_str, UTF8String];
                        if !c_str.is_null() {
                            let s = std::ffi::CStr::from_ptr(c_str)
                                .to_string_lossy()
                                .into_owned();
                            args.push(s);
                        }
                    }
                });
            let open_file_handler = open_file_block.copy();

            // kAEGetURL / GURL
            let clone = Arc::clone(&captured_args);
            let open_url_block =
                ConcreteBlock::new(move |event: *mut Object, _reply: *mut Object| {
                    let list: *mut Object =
                        msg_send![event, paramDescriptorForKeyword: 0x2d2d2d2du32];
                    let count: isize = msg_send![list, numberOfItems];
                    let mut args = clone.lock().unwrap();
                    for i in 1..=count {
                        let desc: *mut Object = msg_send![list, descriptorAtIndex: i];
                        let ns_str: *mut Object = msg_send![desc, stringValue];
                        if ns_str.is_null() {
                            continue;
                        }
                        let c_str: *const std::os::raw::c_char =
                            msg_send![ns_str, UTF8String];
                        if !c_str.is_null() {
                            let s = std::ffi::CStr::from_ptr(c_str)
                                .to_string_lossy()
                                .into_owned();
                            args.push(s);
                        }
                    }
                });
            let open_url_handler = open_url_block.copy();

            let _: () = msg_send![event_manager,
                setEventHandler: &*open_app_handler
                andSelector: sel!(handleAppleEvent:withReplyEvent:)
                forEventClass: 0x61657674u32
                andEventID: 0x6f617070u32];

            let _: () = msg_send![event_manager,
                setEventHandler: &*open_file_handler
                andSelector: sel!(handleAppleEvent:withReplyEvent:)
                forEventClass: 0x61657674u32
                andEventID: 0x6f646f63u32];

            let _: () = msg_send![event_manager,
                setEventHandler: &*open_url_handler
                andSelector: sel!(handleAppleEvent:withReplyEvent:)
                forEventClass: 0x4755524cu32
                andEventID: 0x4755524cu32];
        }

        captured_args
    }

    pub fn process_events(captured_args: &Arc<Mutex<Vec<String>>>, timeout: std::time::Duration) {
        unsafe {
            let ns_app: *mut Object = msg_send![objc::class!(NSApplication), sharedApplication];
            if ns_app.is_null() {
                return;
            }

            let start = std::time::Instant::now();
            let mode_cstr =
                std::ffi::CString::new("kCFRunLoopDefaultMode").unwrap();
            let mode: *mut Object = msg_send![
                objc::class!(NSString),
                stringWithUTF8String: mode_cstr.as_ptr()
            ];

            while start.elapsed() < timeout {
                let pool: *mut Object = msg_send![objc::class!(NSAutoreleasePool), alloc];
                let pool: *mut Object = msg_send![pool, init];

                let date: *mut Object =
                    msg_send![objc::class!(NSDate), distantPast];
                let event: *mut Object = msg_send![ns_app,
                    nextEventMatchingMask: !0u64
                    untilDate: date
                    inMode: mode
                    dequeue: true];
                if !event.is_null() {
                    let _: () = msg_send![ns_app, sendEvent: event];
                }

                let _: () = msg_send![pool, release];

                if !captured_args.lock().unwrap().is_empty() {
                    break;
                }
            }
        }
    }
}

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
            eprintln!(
                "Shim was not able to locate any AYON launcher executables ({}).",
                e
            );
            std::process::exit(1);
        }
    };

    let mut args: Vec<String> = env::args().skip(1).collect();

    // macOS passes a -psn_* argument when launched via Finder; remove it.
    if args.first().map(|a| a.starts_with("-psn_")).unwrap_or(false) {
        args.remove(0);
    }

    let captured_args = macos_events::setup_apple_event_handlers();
    macos_events::process_events(&captured_args, std::time::Duration::from_secs(1));

    {
        let extra = captured_args.lock().unwrap().clone();
        if !extra.is_empty() {
            args.extend(extra);
        }
    }

    let use_open = {
        let s = final_path.to_string_lossy();
        s.contains(".app")
    };

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

    let mut child = match command.spawn() {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Failed to execute {}: {}", final_path.display(), e);
            std::process::exit(1);
        }
    };

    // Keep processing Apple events while the child runs (e.g. URL opens).
    loop {
        match child.try_wait() {
            Ok(Some(status)) => std::process::exit(status.code().unwrap_or(0)),
            Ok(None) => {
                macos_events::process_events(
                    &captured_args,
                    std::time::Duration::from_millis(100),
                );
            }
            Err(e) => {
                eprintln!("Error waiting for subprocess: {}", e);
                std::process::exit(1);
            }
        }
    }
}
