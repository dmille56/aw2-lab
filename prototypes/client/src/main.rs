#[tauri::command]
fn report_connection(app: tauri::AppHandle, connected: bool, message: String) {
    println!("{message}");
    if std::env::var("AW2_CLIENT_SMOKE_TEST").as_deref() == Ok("1") {
        app.exit(if connected { 0 } else { 1 });
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![report_connection])
        .run(tauri::generate_context!())
        .expect("could not run the AW2 client compatibility prototype");
}
