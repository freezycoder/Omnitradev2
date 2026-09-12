fn main() {
    let manifest = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    if let Some(repo) = manifest.parent().and_then(|path| path.parent()) {
        println!("cargo:rustc-env=OMNITRADE_REPO_ROOT={}", repo.display());
    }
    tauri_build::build()
}
