use std::env;
use std::process::Command;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

mod macos_events {
    use super::*;
    use objc2::rc::Retained;
    use objc2::runtime::ProtocolObject;
    use objc2::{declare_class, msg_send, msg_send_id, mutability, sel, ClassType, DeclaredClass};
    use objc2_app_kit::{NSApplication, NSApplicationDelegate};
    use objc2_foundation::{
        MainThreadMarker, NSAppleEventDescriptor, NSAppleEventManager, NSDate, NSNotification,
        NSObject, NSObjectProtocol, NSRunLoopMode, NSString,
    };

    // Constants for Apple Events
    const K_INTERNET_EVENT_CLASS: u32 = 0x4755524c; // 'GURL'
    const K_AE_GET_URL: u32 = 0x4755524c; // 'GURL'
    const KEY_DIRECT_OBJECT: u32 = 0x2d2d2d2d; // '----'

    extern "C" {
        static NSDefaultRunLoopMode: Option<&'static NSRunLoopMode>;
    }

    struct Ivars {
        captured_args: Arc<Mutex<Vec<String>>>,
    }

    declare_class!(
        struct AppDelegate;

        unsafe impl ClassType for AppDelegate {
            type Super = NSObject;
            type Mutability = mutability::MainThreadOnly;
            const NAME: &'static str = "AppDelegate";
        }

        impl DeclaredClass for AppDelegate {
            type Ivars = Ivars;
        }

        unsafe impl NSObjectProtocol for AppDelegate {}

        unsafe impl NSApplicationDelegate for AppDelegate {
            #[method(applicationWillFinishLaunching:)]
            fn application_will_finish_launching(&self, _notification: &NSNotification) {
                let manager = unsafe { NSAppleEventManager::sharedAppleEventManager() };
                unsafe {
                    // Generated objc2 bindings skip this selector, so call it directly.
                    let _: () = msg_send![
                        &manager,
                        setEventHandler: self,
                        andSelector: sel!(handleGetURLEvent:withReplyEvent:),
                        forEventClass: K_INTERNET_EVENT_CLASS,
                        andEventID: K_AE_GET_URL
                    ];
                }
            }
        }

        unsafe impl AppDelegate {
            #[method(handleGetURLEvent:withReplyEvent:)]
            fn handle_get_url_event(
                &self,
                event: &NSAppleEventDescriptor,
                _reply_event: &NSAppleEventDescriptor,
            ) {
                let desc: Option<Retained<NSAppleEventDescriptor>> = unsafe {
                    msg_send_id![event, paramDescriptorForKeyword: KEY_DIRECT_OBJECT]
                };

                if let Some(desc) = desc {
                    let url_spec: Option<Retained<NSString>> = unsafe { msg_send_id![&desc, stringValue] };
                    if let Some(url_spec) = url_spec {
                        let mut args = self.ivars().captured_args.lock().unwrap();
                        args.push(url_spec.to_string());
                    }
                }
            }
        }
    );

    impl AppDelegate {
        fn new(mtm: MainThreadMarker, captured_args: Arc<Mutex<Vec<String>>>) -> Retained<Self> {
            let this = mtm.alloc();
            let this = this.set_ivars(Ivars { captured_args });
            unsafe { msg_send_id![super(this), init] }
        }
    }

    pub fn capture_apple_events() -> Vec<String> {
        let mtm = MainThreadMarker::new().expect("Must be on the main thread");
        let captured_args = Arc::new(Mutex::new(Vec::new()));

        let app = NSApplication::sharedApplication(mtm);
        let delegate = AppDelegate::new(mtm, Arc::clone(&captured_args));
        let protocol_delegate = ProtocolObject::from_retained(delegate);
        app.setDelegate(Some(&protocol_delegate));

        // We don't call app.run() because we want to return.
        // Instead, we pump the event loop for a short time.
        let timeout = Duration::from_secs(1);
        let start = Instant::now();

        while start.elapsed() < timeout {
            let until = unsafe { NSDate::dateWithTimeIntervalSinceNow(0.1) };
            let mode = unsafe { NSDefaultRunLoopMode }.expect("NSDefaultRunLoopMode unavailable");
            let event = unsafe {
                app.nextEventMatchingMask_untilDate_inMode_dequeue(
                    objc2_app_kit::NSEventMask::from_bits_retain(u64::MAX), // NSEventMaskAny
                    Some(&until),
                    mode,
                    true,
                )
            };

            if let Some(event) = event {
                unsafe { app.sendEvent(&event) };
            }

            if !captured_args.lock().unwrap().is_empty() {
                break;
            }
        }

        let final_args = captured_args.lock().unwrap().clone();
        final_args
    }
}

fn main() {
    let mut args: Vec<String> = env::args().collect();
    if !args.is_empty() {
        args.remove(0);
    }

    // Remove -psn_ argument if present (passed by macOS when launching .app)
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

    // Launch the actual ayon shim
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
