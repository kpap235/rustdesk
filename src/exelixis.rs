//! Exelixisnet IT Support: variant selection and customer registration.
//!
//! One Windows binary ships as two tools, chosen by its file name (see
//! `init_variant`): `exSupport` is the full build for technicians, and
//! `exQuickSupport` is the locked customer build (always so on Android).
//!
//! QuickSupport registers itself with the support panel with no questions: it
//! sets a hidden random permanent password, reports the computer name, local IP
//! and signed-in user, and sends a heartbeat every minute so technicians can see
//! who is online and connect. It re-registers by itself if the panel lost it.
//! The full technician build never registers as a customer device.
//!
//! State lives in the shared service config (Config options), so it survives
//! restarts and is visible to both the UI and the service:
//!   exelixis-name, exelixis-phone   what the customer typed
//!   exelixis-secret                 per-device secret issued by the panel
//!   exelixis-pw                     the permanent password we generated
//!   exelixis-id                     the ID last reported (to detect changes)

use hbb_common::{
    config::Config,
    log,
    rand::{distributions::Alphanumeric, Rng},
    serde_json::{self, json},
    tokio, ResultType,
};

const PANEL_URL: &str = match option_env!("EXELIXIS_PANEL_URL") {
    Some(v) => v,
    None => "https://rustdesk.exelixisnet.gr",
};
const ENROLL_TOKEN: &str = match option_env!("EXELIXIS_ENROLL_TOKEN") {
    Some(v) => v,
    None => "",
};
const EXELIXIS_VERSION: &str = match option_env!("EXELIXIS_VERSION") {
    Some(v) => v,
    None => "dev",
};
const HEARTBEAT_SECS: u64 = 60;

pub const OPT_NAME: &str = "exelixis-name";
pub const OPT_PHONE: &str = "exelixis-phone";
pub const OPT_SECRET: &str = "exelixis-secret";
pub const OPT_PW: &str = "exelixis-pw";
pub const OPT_ID: &str = "exelixis-id";

static SUPPORT_STARTED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// QuickSupport (customer) variant vs the full technician variant.
///
/// Android is always QuickSupport. On desktop one binary serves both roles and
/// the file name decides: `exQuickSupport.exe` is the locked customer build,
/// anything else (`exSupport.exe`) is the full build. The portable packer sets
/// `RUSTDESK_APPNAME`, so that is honoured too.
pub fn is_quick_support() -> bool {
    #[cfg(any(target_os = "android", target_os = "ios"))]
    {
        true
    }
    #[cfg(not(any(target_os = "android", target_os = "ios")))]
    {
        let from_env = std::env::var("RUSTDESK_APPNAME")
            .map(|v| v.to_lowercase().contains("quick"))
            .unwrap_or(false);
        let from_exe = std::env::current_exe()
            .ok()
            .and_then(|p| p.file_stem().map(|s| s.to_string_lossy().to_lowercase()))
            .map(|s| s.contains("quick"))
            .unwrap_or(false);
        from_env || from_exe
    }
}

/// Sets the app name and, for QuickSupport, the locked-down settings. Called as
/// early as possible (right after `load_custom_client`) in every process so the
/// app name is consistent before any install, config path or service command.
pub fn init_variant() {
    let app_name = if is_quick_support() {
        "exQuickSupport"
    } else {
        "exSupport"
    };
    *hbb_common::config::APP_NAME.write().unwrap() = app_name.to_owned();

    if !is_quick_support() {
        return;
    }

    // Incoming connections only, and no settings the customer could change.
    {
        let mut hard = hbb_common::config::HARD_SETTINGS.write().unwrap();
        hard.insert("conn-type".to_owned(), "incoming".to_owned());
        hard.insert("disable-settings".to_owned(), "Y".to_owned());
    }
    // WebSocket off: a customer who turns it on cannot connect to our server.
    hbb_common::config::OVERWRITE_SETTINGS
        .write()
        .unwrap()
        .insert("allow-websocket".to_owned(), "N".to_owned());
}

/// The computer's LAN address, for the technician to recognise the machine.
fn local_ip() -> String {
    std::net::UdpSocket::bind("0.0.0.0:0")
        .and_then(|s| {
            s.connect("1.1.1.1:80")?;
            s.local_addr()
        })
        .map(|a| a.ip().to_string())
        .unwrap_or_default()
}

/// The interactive Windows user (the service runs as SYSTEM, so ask the OS);
/// the login name elsewhere.
fn os_user() -> String {
    #[cfg(windows)]
    {
        let u = crate::platform::windows::get_active_username();
        if !u.is_empty() {
            return u;
        }
    }
    crate::username()
}

fn kind() -> &'static str {
    if is_quick_support() {
        "quick"
    } else {
        "full"
    }
}

/// Service/host-process start-up for QuickSupport: make sure the hidden access
/// password and the computer name are stored, then lock the password so the
/// customer can never change it, and begin reporting to the panel.
///
/// Idempotent and safe to call from whichever process actually hosts the
/// session (the installed `--server`, or the portable/Android main process).
///
/// Only QuickSupport reports to the panel. The full technician build (exSupport)
/// never registers itself as a customer device.
pub fn start_support() {
    if !is_quick_support() {
        return;
    }
    if SUPPORT_STARTED.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    ensure_quick_registration();
    start_heartbeat();
}

/// Stores the hidden permanent password and the computer name, then blocks any
/// later change to the permanent password. The password MUST be set before the
/// lock: `Config::set_permanent_password` refuses once the lock is in place.
fn ensure_quick_registration() {
    if !Config::has_permanent_password() {
        let pw = random_password();
        if Config::set_permanent_password(&pw) {
            Config::set_option(OPT_PW.to_owned(), pw);
        } else {
            log::error!("exelixis: could not set the hidden access password");
        }
    }
    if Config::get_option(OPT_NAME).is_empty() {
        let name = hostname();
        if !name.is_empty() {
            Config::set_option(OPT_NAME.to_owned(), name);
        }
    }
    hbb_common::config::BUILTIN_SETTINGS.write().unwrap().insert(
        "disable-change-permanent-password".to_owned(),
        "Y".to_owned(),
    );
}

/// Name shown to people (window titles, texts). The internal app name has no
/// spaces because Windows service commands use it unquoted.
pub fn display_name() -> String {
    let name = crate::get_app_name();
    match name.as_str() {
        "ExelixisnetITSupport" | "exSupport" | "exQuickSupport" => {
            "Exelixisnet IT Support".to_owned()
        }
        _ => name,
    }
}

/// Our release number plus the RustDesk version it is built on, e.g. "1.0.0 (RustDesk 1.5.1)".
pub fn version_text() -> String {
    let ours = if EXELIXIS_VERSION.is_empty() { "dev" } else { EXELIXIS_VERSION };
    format!("{} (RustDesk {})", ours, crate::VERSION)
}

fn hostname() -> String {
    hbb_common::whoami::fallible::hostname().unwrap_or_default()
}

fn parse_version(v: &str) -> Option<(u32, u32, u32)> {
    let mut it = v.trim().split('.');
    let a = it.next()?.parse().ok()?;
    let b = it.next().unwrap_or("0").parse().ok()?;
    let c = it.next().unwrap_or("0").parse().ok()?;
    Some((a, b, c))
}

fn is_newer(latest: &str, current: &str) -> bool {
    match (parse_version(latest), parse_version(current)) {
        (Some(l), Some(c)) => l > c,
        _ => false, // unknown / dev build: don't nag
    }
}

/// The customer pressed "Call for help": raise a support request on the panel.
/// Returns an empty string on success, otherwise a message to show.
pub fn call_for_help(message: String) -> String {
    match call_for_help_blocking(message.trim()) {
        Ok(()) => String::new(),
        Err(e) => format!("{e}"),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn call_for_help_blocking(message: &str) -> ResultType<()> {
    let id = Config::get_id();
    let secret = Config::get_option(OPT_SECRET);
    if id.is_empty() || secret.is_empty() {
        hbb_common::bail!("This computer is not registered with support yet.");
    }
    let body = json!({ "id": id, "secret": secret, "message": message });
    let (status, text) = post("/api/client/request", body, false).await?;
    if status != 200 {
        hbb_common::bail!("Support server answered {}: {}", status, text);
    }
    Ok(())
}

/// Checks the panel for a newer app version. Returns a JSON string
/// `{"version":"x","url":"y"}` when an update is available, otherwise empty.
/// Does a blocking network call, so call it off the UI thread.
pub fn check_update() -> String {
    match check_update_blocking() {
        Ok(Some((version, url))) => json!({"version": version, "url": url}).to_string(),
        _ => String::new(),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn check_update_blocking() -> ResultType<Option<(String, String)>> {
    let (status, text) = post("/api/appversion", json!({}), false).await?;
    if status != 200 {
        return Ok(None);
    }
    let v: serde_json::Value = serde_json::from_str(&text)?;
    let latest = v.get("version").and_then(|x| x.as_str()).unwrap_or("");
    if latest.is_empty() || !is_newer(latest, EXELIXIS_VERSION) {
        return Ok(None);
    }
    let (key, path) = if cfg!(target_os = "android") {
        ("android", "/get/android")
    } else if is_quick_support() {
        ("windows_quick", "/get/quick")
    } else {
        ("windows_full", "/get/exsupport")
    };
    let url = v
        .get(key)
        .and_then(|x| x.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_owned())
        .unwrap_or_else(|| format!("{}{}", PANEL_URL, path));
    Ok(Some((latest.to_owned(), url)))
}

fn os_name() -> String {
    hbb_common::whoami::distro()
}

/// (os, ram, disk) for the panel: a detailed OS name (e.g. "Windows 11 Pro"),
/// total RAM and the largest disk's size, as human strings.
fn hardware() -> (String, String, String) {
    use hbb_common::sysinfo::{Disks, System};
    let mut sys = System::new();
    sys.refresh_memory();
    let ram_gb = (sys.total_memory() as f64 / 1024.0 / 1024.0 / 1024.0).round() as u64;
    let ram = if ram_gb > 0 {
        format!("{} GB", ram_gb)
    } else {
        String::new()
    };
    let os = match sys.long_os_version() {
        Some(v) if !v.is_empty() => v,
        _ => os_name(),
    };
    let disks = Disks::new_with_refreshed_list();
    let disk_bytes = disks.iter().map(|d| d.total_space()).max().unwrap_or(0);
    let disk = if disk_bytes > 0 {
        format!("{} GB", (disk_bytes as f64 / 1e9).round() as u64)
    } else {
        String::new()
    };
    (os, ram, disk)
}

fn random_password() -> String {
    // Letters and digits only: safe in URLs and easy to read out on the phone.
    hbb_common::rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(14)
        .map(char::from)
        .collect()
}

async fn post(path: &str, body: serde_json::Value, with_token: bool) -> ResultType<(u16, String)> {
    let header = if with_token {
        format!("X-Enroll-Token: {}", ENROLL_TOKEN)
    } else {
        String::new()
    };
    crate::post_request_with_status(format!("{}{}", PANEL_URL, path), body.to_string(), &header)
        .await
}

/// Registers with the panel; returns the device secret.
async fn register_remote(id: &str, name: &str, phone: &str, password: &str) -> ResultType<String> {
    if ENROLL_TOKEN.is_empty() {
        hbb_common::bail!("This build has no enrollment token");
    }
    let (os, ram, disk) = hardware();
    let body = json!({
        "id": id,
        "name": name,
        "phone": phone,
        "hostname": hostname(),
        "os": os,
        "ram": ram,
        "disk": disk,
        "version": version_text(),
        "password": password,
        "local_ip": local_ip(),
        "os_user": os_user(),
        "kind": kind(),
    });
    let (status, text) = post("/api/client/register", body, true).await?;
    if status != 200 {
        hbb_common::bail!("Support server answered {}: {}", status, text);
    }
    let v: serde_json::Value = serde_json::from_str(&text)?;
    match v.get("secret").and_then(|s| s.as_str()) {
        Some(s) if !s.is_empty() => Ok(s.to_owned()),
        _ => hbb_common::bail!("Support server sent no device secret"),
    }
}

// ---------------------------------------------------------------------------
// UI side (called from Flutter through flutter_ffi.rs)
// ---------------------------------------------------------------------------

/// True when this is an installed copy whose customer has not registered yet.
#[cfg(not(any(target_os = "android", target_os = "ios")))]
pub fn needs_registration() -> bool {
    // QuickSupport registers itself with the computer name, and the full
    // technician build does not register at all, so the name dialog never shows.
    false
}

#[cfg(any(target_os = "android", target_os = "ios"))]
pub fn needs_registration() -> bool {
    false
}

/// Called when the customer presses OK in the name window.
/// Returns an empty string on success, otherwise a message to show.
#[cfg(not(any(target_os = "android", target_os = "ios")))]
pub fn register(name: String, phone: String) -> String {
    let name = name.trim().to_owned();
    let phone = phone.trim().to_owned();
    if name.is_empty() {
        return "Please enter your name or company name.".to_owned();
    }
    let password = random_password();
    if !crate::ui_interface::set_permanent_password_with_result(password.clone()) {
        return "Could not set the access password on this computer.".to_owned();
    }
    let id = crate::ipc::get_id();
    match register_blocking(&id, &name, &phone, &password) {
        Ok(secret) => {
            let mut options = crate::ipc::get_options();
            options.insert(OPT_NAME.to_owned(), name);
            options.insert(OPT_PHONE.to_owned(), phone);
            options.insert(OPT_PW.to_owned(), password);
            options.insert(OPT_SECRET.to_owned(), secret);
            options.insert(OPT_ID.to_owned(), id);
            if let Err(e) = crate::ipc::set_options(options) {
                log::error!("exelixis: saving registration failed: {e}");
                return "Registered, but saving the settings failed. Please restart the app."
                    .to_owned();
            }
            log::info!("exelixis: registered with support panel");
            String::new()
        }
        Err(e) => {
            log::error!("exelixis: registration failed: {e}");
            // Keep name and password so the service can finish registering on its own later.
            let mut options = crate::ipc::get_options();
            options.insert(OPT_NAME.to_owned(), name);
            options.insert(OPT_PHONE.to_owned(), phone);
            options.insert(OPT_PW.to_owned(), password);
            crate::ipc::set_options(options).ok();
            "Could not reach the Exelixisnet support server right now. It will retry automatically - you can close this window.".to_owned()
        }
    }
}

#[cfg(any(target_os = "android", target_os = "ios"))]
pub fn register(_name: String, _phone: String) -> String {
    "Not supported on this device".to_owned()
}

#[tokio::main(flavor = "current_thread")]
async fn register_blocking(
    id: &str,
    name: &str,
    phone: &str,
    password: &str,
) -> ResultType<String> {
    register_remote(id, name, phone, password).await
}

// ---------------------------------------------------------------------------
// Service side: heartbeat loop
// ---------------------------------------------------------------------------

/// Starts the heartbeat thread. Call once from the service process.
pub fn start_heartbeat() {
    if ENROLL_TOKEN.is_empty() {
        return;
    }
    std::thread::Builder::new()
        .name("exelixis-heartbeat".into())
        .spawn(|| loop {
            if let Err(e) = heartbeat_once() {
                log::debug!("exelixis: heartbeat failed: {e}");
            }
            std::thread::sleep(std::time::Duration::from_secs(HEARTBEAT_SECS));
        })
        .ok();
}

// ---------------------------------------------------------------------------
// Session reporting: measure how long a technician is connected
// ---------------------------------------------------------------------------

// One key per active support period on this device (first remote connection in
// to last one out). Kept here so the "end" report pairs with its "start".
static CURRENT_SESSION_KEY: std::sync::Mutex<String> = std::sync::Mutex::new(String::new());

/// A remote-control connection was authorized. Call when the count of live
/// remote connections rises to one (the start of a support session).
pub fn on_remote_session_start() {
    if ENROLL_TOKEN.is_empty() {
        return;
    }
    let key = {
        let mut k = match CURRENT_SESSION_KEY.lock() {
            Ok(k) => k,
            Err(_) => return,
        };
        if k.is_empty() {
            *k = format!("{}-{}", std::process::id(), random_password());
        }
        k.clone()
    };
    report_session("start", key);
}

/// The last remote-control connection closed (the end of a support session).
pub fn on_remote_session_end() {
    if ENROLL_TOKEN.is_empty() {
        return;
    }
    let key = {
        let mut k = match CURRENT_SESSION_KEY.lock() {
            Ok(k) => k,
            Err(_) => return,
        };
        let key = k.clone();
        k.clear();
        key
    };
    if !key.is_empty() {
        report_session("end", key);
    }
}

fn report_session(event: &'static str, session_key: String) {
    std::thread::Builder::new()
        .name("exelixis-session".into())
        .spawn(move || {
            if let Err(e) = report_session_blocking(event, &session_key) {
                log::debug!("exelixis: session report failed: {e}");
            }
        })
        .ok();
}

#[tokio::main(flavor = "current_thread")]
async fn report_session_blocking(event: &str, session_key: &str) -> ResultType<()> {
    let id = Config::get_id();
    let secret = Config::get_option(OPT_SECRET);
    if id.is_empty() || secret.is_empty() {
        return Ok(()); // not an enrolled support device
    }
    let body = json!({
        "id": id,
        "secret": secret,
        "event": event,
        "session_key": session_key,
    });
    let (status, text) = post("/api/client/session", body, false).await?;
    if status != 200 {
        hbb_common::bail!("session {} answered {}: {}", event, status, text);
    }
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn heartbeat_once() -> ResultType<()> {
    let name = Config::get_option(OPT_NAME);
    let password = Config::get_option(OPT_PW);
    if name.is_empty() || password.is_empty() {
        return Ok(()); // customer has not filled in the name window yet
    }
    let id = Config::get_id();
    if id.is_empty() {
        return Ok(());
    }
    let mut secret = Config::get_option(OPT_SECRET);
    let last_id = Config::get_option(OPT_ID);

    if !secret.is_empty() {
        let (os, ram, disk) = hardware();
        let mut body = json!({
            "id": id,
            "secret": secret,
            "version": version_text(),
            "hostname": hostname(),
            "os": os,
            "ram": ram,
            "disk": disk,
            "local_ip": local_ip(),
            "os_user": os_user(),
            "kind": kind(),
        });
        if !last_id.is_empty() && last_id != id {
            body["old_id"] = json!(last_id);
        }
        let (status, text) = post("/api/client/heartbeat", body, false).await?;
        match status {
            200 => {
                if last_id != id {
                    Config::set_option(OPT_ID.to_owned(), id);
                }
                return Ok(());
            }
            401 | 404 => {
                log::info!("exelixis: panel does not know this device, registering again");
                secret.clear();
            }
            _ => hbb_common::bail!("heartbeat answered {}: {}", status, text),
        }
    }

    // Not registered yet (UI could not reach the panel) or the panel forgot us.
    let phone = Config::get_option(OPT_PHONE);
    let new_secret = register_remote(&id, &name, &phone, &password).await?;
    Config::set_option(OPT_SECRET.to_owned(), new_secret);
    Config::set_option(OPT_ID.to_owned(), id);
    log::info!("exelixis: registered with support panel from the service");
    Ok(())
}
