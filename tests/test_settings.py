from pathlib import Path

from monash_ed_downloader.settings import Settings


def test_default_paths_keep_output_and_private_state_separate(tmp_path: Path) -> None:
    settings = Settings.default(home=tmp_path)
    assert settings.output_root == tmp_path / "Desktop" / "Monash ED Downloads"
    assert settings.state_root != settings.output_root
    assert settings.database.parent == settings.state_root
