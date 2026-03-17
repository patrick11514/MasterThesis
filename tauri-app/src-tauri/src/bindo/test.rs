use rayon::iter::{ParallelBridge, ParallelIterator};
use walkdir::WalkDir;

#[tokio::main]
async fn main() {
    let dir = WalkDir::new("/home/patrick115/Projects/VSB");

    let files = dir
        .into_iter()
        .par_bridge()
        .filter_map(|file| {
            if let Ok(file) = file {
                Some(file)
            } else {
                None
            }
        })
        .filter_map(|file| {
            if let Some(ext) = &file.path().extension() {
                if ext == &"fits" {
                    Some(file.path().to_owned())
                } else {
                    None
                }
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    println!("{}", files.len());
}
