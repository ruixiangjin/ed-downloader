from pathlib import Path

from monash_ed_downloader.auth import (
    clear_login_confirmation,
    has_confirmed_login,
    mark_login_confirmed,
)
from monash_ed_downloader.settings import Settings


def settings_for(tmp_path: Path) -> Settings:
    return Settings(output_root=tmp_path / "output", state_root=tmp_path / "state")


def test_login_marker_only_exists_after_confirmation(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    assert not has_confirmed_login(settings)
    mark_login_confirmed(settings)
    assert has_confirmed_login(settings)
    assert settings.login_marker.stat().st_mode & 0o777 == 0o600
    clear_login_confirmation(settings)
    assert not has_confirmed_login(settings)


def test_damaged_login_marker_is_not_confirmation(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    settings.state_root.mkdir()
    settings.login_marker.write_text("not json", encoding="utf-8")
    assert not has_confirmed_login(settings)
