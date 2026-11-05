#[tauri::command]
fn report_connection(app: tauri::AppHandle, connected: bool, message: String) {
    println!("{message}");
    if std::env::var("AW2_CLIENT_SMOKE_TEST").as_deref() == Ok("1") {
        app.exit(if connected { 0 } else { 1 });
    }
}

#[tauri::command]
fn client_api_base() -> String {
    let port = std::env::var("AW2_CLIENT_API_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|port| *port != 0)
        .unwrap_or(43127);
    format!("http://127.0.0.1:{port}")
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![report_connection, client_api_base])
        .run(tauri::generate_context!())
        .expect("could not run the AW2 client compatibility prototype");
}
