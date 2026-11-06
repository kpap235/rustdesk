//! Exelixisnet IT Support: customer registration with the support panel.
//!
//! On first start after installation the app asks the customer for their name
//! (see flutter/lib/desktop/widgets/exelixis_register.dart). `register` then
//! sets a random permanent password and sends ID, name and password to the
//! panel. The service process sends a heartbeat every minute so technicians
//! can see who is online, and re-registers by itself if the panel lost it.
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

/// Name shown to people (window titles, texts). The internal app name has no
/// spaces because Windows service commands use it unquoted.
pub fn display_name() -> String {
    let name = crate::get_app_name();
    if name == "ExelixisnetITSupport" {
        "Exelixisnet IT Support".to_owned()
    } else {
        name
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

fn os_name() -> String {
    hbb_common::whoami::distro()
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
    let body = json!({
        "id": id,
        "name": name,
        "phone": phone,
        "hostname": hostname(),
        "os": os_name(),
        "version": version_text(),
        "password": password,
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
    if !crate::platform::is_installed() || ENROLL_TOKEN.is_empty() {
        return false;
    }
    let options = crate::ipc::get_options();
    options
        .get(OPT_SECRET)
        .map(|s| s.is_empty())
        .unwrap_or(true)
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
        let mut body = json!({
            "id": id,
            "secret": secret,
            "version": version_text(),
            "hostname": hostname(),
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
