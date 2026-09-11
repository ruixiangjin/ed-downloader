class EdDownloaderError(RuntimeError):
    """Base error safe to show to the user."""


class LoginRequiredError(EdDownloaderError):
    """The saved Ed session is absent or expired."""


class BrowserUnavailableError(EdDownloaderError):
    """Chrome cannot be launched with the private profile."""


class CourseNotFoundError(EdDownloaderError):
    """No accessible course matched the supplied selector."""


class SyncSafetyError(EdDownloaderError):
    """A sync would risk replacing complete data with incomplete data."""
