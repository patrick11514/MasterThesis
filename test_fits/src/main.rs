fn main() -> anyhow::Result<()> {
    let keys = vec![
        "IMAGETYP", "COLORTYP", "EXPTIME", "EXPOSURE", "CCD-TEMP", "SET-TEMP", "GAIN", "EGAIN",
        "DATE-OBS", "FILTER", "XBINNING", "YBINNING", "XBAYROFF", "YBAYROFF",
    ];

    for file in glob::glob("*.fit*")? {
        let file = file?;
        println!("\nfile = {:?}", &file.display());
        let mut file = fitsio::FitsFile::open(file)?;
        let hdu = file.primary_hdu()?;

        let info = &hdu.info;

        if let fitsio::hdu::HduInfo::ImageInfo { shape, image_type } = info {
            println!("shape = {:?}, image_type = {:?}", shape, image_type);
        }

        for key in &keys {
            if let Ok(value) = hdu.read_key::<fitsio::headers::HeaderValue<String>>(&mut file, key)
            {
                println!("{} = {:?}", key, value.value);
            } else {
                println!("{} = None", key);
            }
        }
    }

    Ok(())
}
