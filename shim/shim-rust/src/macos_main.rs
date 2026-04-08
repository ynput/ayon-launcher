use std::env;
use std::process::Command;

#[cfg(not(target_os = "macos"))]
fn main() {
    eprintln!("Error: 'ayon_macos' is only supported on macOS.");
    std::process::exit(1);
}

#[cfg(target_os = "macos")]
mod macos_events {
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, Instant};
    use objc::runtime::Object;
    use objc::{msg_send, sel, sel_impl};
    use block::ConcreteBlock;

    pub fn capture_apple_events() -> Vec<String> {
        let captured_args = Arc::new(Mutex::new(Vec::new()));

        unsafe {
            let event_manager: *mut Object = msg_send![objc::class!(NSAppleEventManager), sharedAppleEventManager];

            let captured_args_clone = Arc::clone(&captured_args);
            let open_app_block = ConcreteBlock::new(move |_event: *mut Object, _reply_event: *mut Object| {
                // Do nothing
            });
            let open_app_handler = open_app_block.copy();

            let captured_args_clone = Arc::clone(&captured_args);
            let open_file_block = ConcreteBlock::new(move |event: *mut Object, _reply_event: *mut Object| {
                let list: *mut Object = msg_send![event, paramDescriptorForKeyword: 0x2d2d2d2d];
                let count: isize = msg_send![list, numberOfItems];
                let mut args = captured_args_clone.lock().unwrap();
                for i in 1..=count {
                    let desc: *mut Object = msg_send![list, descriptorAtIndex: i];
                    let path: *mut Object = msg_send![desc, stringValue];
                    if !path.is_null() {
                        let c_str: *const std::os::raw::c_char = msg_send![path, UTF8String];
                        if !c_str.is_null() {
                            let s = std::ffi::CStr::from_ptr(c_str).to_string_lossy().into_owned();
                            args.push(s);
                        }
                    }
                }
            });
            let open_file_handler = open_file_block.copy();

            let captured_args_clone = Arc::clone(&captured_args);
            let open_url_block = ConcreteBlock::new(move |event: *mut Object, _reply_event: *mut Object| {
                let list: *mut Object = msg_send![event, paramDescriptorForKeyword: 0x2d2d2d2d];
                let count: isize = msg_send![list, numberOfItems];
                let mut args = captured_args_clone.lock().unwrap();
                for i in 1..=count {
                    let desc: *mut Object = msg_send![list, descriptorAtIndex: i];
                    let url: *mut Object = msg_send![desc, stringValue];
                    if !url.is_null() {
                        let c_str: *const std::os::raw::c_char = msg_send![url, UTF8String];
                        if !c_str.is_null() {
                            let s = std::ffi::CStr::from_ptr(c_str).to_string_lossy().into_owned();
                            args.push(s);
                        }
                    }
                }
            });
            let open_url_handler = open_url_block.copy();

            let _: () = msg_send![event_manager, setEventHandler: &*open_app_handler
                                               andSelector: sel!(handleAppleEvent:withReplyEvent:)
                                             forEventClass: 0x61657674
                                                andEventID: 0x6f617070];

            let _: () = msg_send![event_manager, setEventHandler: &*open_file_handler
                                               andSelector: sel!(handleAppleEvent:withReplyEvent:)
                                             forEventClass: 0x61657674
                                                andEventID: 0x6f646f63];

            let _: () = msg_send![event_manager, setEventHandler: &*open_url_handler
                                               andSelector: sel!(handleAppleEvent:withReplyEvent:)
                                             forEventClass: 0x4755524c
                                                andEventID: 0x4755524c];

            let ns_app: *mut Object = msg_send![objc::class!(NSApplication), sharedApplication];
            let timeout = Duration::from_secs(1);
            let start = Instant::now();

            while start.elapsed() < timeout {
                let date: *mut Object = msg_send![objc::class!(NSDate), dateWithTimeIntervalSinceNow: 0.1];
                let event: *mut Object = msg_send![ns_app, nextEventMatchingMask: !0
                                                                    untilDate: date
                                                                        inMode: std::ptr::null_mut::<Object>()
                                                                      dequeue: true];
                if !event.is_null() {
                    let _: () = msg_send![ns_app, sendEvent: event];
                }

                if !captured_args.lock().unwrap().is_empty() {
                    break;
                }
            }
        }

        let final_captured = captured_args.lock().unwrap().clone();
        final_captured
    }
}

#[cfg(target_os = "macos")]
fn main() {
    let mut args: Vec<String> = env::args().collect();
    if !args.is_empty() {
        args.remove(0);
    }

    if !args.is_empty() && args[0].starts_with("-psn_") {
        args.remove(0);
    }

    let captured = macos_events::capture_apple_events();
    if !captured.is_empty() {
        args.extend(captured);
    }

    let exe_path = env::current_exe().expect("Failed to get current executable path");
    let macos_root = exe_path.parent().expect("Failed to get executable parent directory");
    let ayon_shim = macos_root.join("ayon");

    let mut command = Command::new("open");
    command.arg("-na").arg(&ayon_shim);
    if !args.is_empty() {
        command.arg("--args").args(&args);
    }

    match command.status() {
        Ok(status) => {
            std::process::exit(status.code().unwrap_or(0));
        }
        Err(e) => {
            eprintln!("Failed to execute {}: {}", ayon_shim.display(), e);
            std::process::exit(1);
        }
    }
}
