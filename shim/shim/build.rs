fn main() {
    #[cfg(target_os = "windows")]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("../../common/ayon_common/resources/AYON.ico");
        res.compile().unwrap();
    }
}
