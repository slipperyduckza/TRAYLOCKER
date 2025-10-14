use std::env;
use std::fs;
use std::path::Path;

fn main() {
    let svg_bytes = include_bytes!("keyboard.svg");
    let out_dir = env::var("OUT_DIR").unwrap();
    let svg_path = Path::new(&out_dir).join("keyboard.svg");
    fs::write(&svg_path, svg_bytes).unwrap();
    let ico_path = Path::new(&out_dir).join("icon.ico");
    svg_to_ico::svg_to_ico(&svg_path, 1.0, &ico_path, &[256, 128, 48, 32, 24, 16]).unwrap();

    let ico_path_str = ico_path.to_string_lossy().replace('\\', "/");
    let rc_content = format!("1 ICON \"{}\"", ico_path_str);
    let rc_path = Path::new(&out_dir).join("resource.rc");
    fs::write(&rc_path, rc_content).unwrap();

    embed_resource::compile(rc_path, embed_resource::NONE);
}