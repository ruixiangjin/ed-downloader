from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


@dataclass(frozen=True, slots=True)
class Settings:
    output_root: Path
    state_root: Path
    ed_base_url: str = "https://edstem.org"
    region: str = "au"

    @classmethod
    def default(cls, *, home: Path | None = None) -> Settings:
        resolved_home = home if home is not None else Path.home()
        return cls(
            output_root=resolved_home / "Desktop" / "Monash ED Downloads",
            state_root=Path(user_data_path("Monash ED Downloader", "ruixiangjin")),
        )

    @property
    def browser_profile(self) -> Path:
        return self.state_root / "playwright-profile"

    @property
    def storage_state(self) -> Path:
        return self.state_root / "ed-storage-state.json"

    @property
    def login_marker(self) -> Path:
        return self.state_root / "login-confirmed.json"

    @property
    def database(self) -> Path:
        return self.state_root / "state.sqlite3"
