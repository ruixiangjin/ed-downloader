[**English**](README.md) | [简体中文](README.zh-CN.md)

# Monash ED Downloader

A read-only cross-platform command-line tool that synchronises Ed Discussions, Lessons, and non-media
attachments that your own account is authorised to access for offline study. It uses a dedicated
Chrome profile for Monash SSO and MFA, and it does not read Ed Workspaces.

Login data and the incremental database are kept in the operating system's private per-user data
directory. Course materials are saved to the current user's Desktop under `Monash ED Downloads` by
default, outside the Git repository.

## What it saves

- A persistent Discussions JSON file for each course, including threads, answers, comments,
  categories, accepted-answer state, authors, roles, timestamps, image links, and incremental Tags.
- Lesson text, supported slide content, quiz questions and answer options, and Ed-designated
  `webpage` lessons as Markdown.
- PDF, Office, ZIP, CSV, text, code, and other confirmed direct non-media attachments.
- A versioned `<course name> - Last Sync.json` for Lessons, containing the latest detected groups,
  lesson structure, resource status, and sync result.
- Ordinary external webpages and all media as links only.

Images, video, audio, and fonts are not downloaded. Ordinary external webpages are recorded as
links; when Ed itself defines a Lesson slide as `webpage`, that page is treated as course content
and saved as Markdown. This covers externally hosted lesson pages that Ed designates as course
content.
ZIP files are saved without extraction, and downloaded documents are not converted.

## For regular users: double-click to start

Regular users need Google Chrome and an internet connection for the first launch. They do not need
to install Python, uv, or development tools manually.

1. Download or clone this repository.
2. On Windows, double-click `Monash ED Downloader.cmd`. On a Mac, double-click
   `Monash ED Downloader.command`.
3. On the first launch, wait while the launcher downloads the official uv runtime and prepares only
   the Python version and application dependencies needed to run ED Downloader.
4. Complete Monash SSO and MFA in the Chrome window when prompted, then use the numbered menu.

The automatic runtime is isolated in the operating system's private per-user data directory. On
Windows this is normally `%LOCALAPPDATA%\Monash ED Downloader\`; on a Mac it is normally
`~/Library/Application Support/Monash ED Downloader/`. It does not change the system Python,
`PATH`, or shell configuration. Later launches reuse this environment and are faster.

If the operating system blocks the launcher on its first opening, use its standard **Open** or
security-confirmation option. If environment preparation fails, check the internet connection and
double-click the launcher again.

## For developers: Terminal setup

Developers manage their own environment from Terminal. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```console
git clone https://github.com/ruixiangjin/ed-downloader.git
cd ed-downloader
uv sync --all-groups
uv run ed-downloader --help
uv run ed-downloader sync --help
```

Use `uv run ed-downloader ...` for development commands. The double-click launchers are intended
for regular users and deliberately exclude the `dev` dependency group.

## First login

```console
uv run ed-downloader login
uv run ed-downloader doctor
uv run ed-downloader courses
uv run ed-downloader menu
```

`login` opens a dedicated Chrome window. Complete Monash SSO and MFA only in that window, wait until
an Ed course page is visible, then return to the terminal and press Enter. The tool never accepts or
saves your password or verification code. It checks for a visible signed-in user instead of treating
the mere existence of a browser profile as a successful login.

If a later command detects an expired session, the tool clears its login confirmation, opens the
login flow, and retries the requested operation once. You can also run `ed-downloader login` again
manually.

`courses` and `menu` display current courses separately from courses archived by semester. An
archived course can still be selected explicitly by course code or numeric Ed course ID.

## Interactive terminal menu

Developers can run `uv run ed-downloader menu`. Regular users can double-click the launcher for
their operating system. Both launchers find the repository from their own location, so the project
folder can be stored anywhere and no user-specific path is embedded.

The menu provides these choices:

1. Incrementally synchronise Discussions and Lessons for every current course.
2. Select one current or semester-archived course, then synchronise the entire course.
3. Select one course, then synchronise Discussions only or all Lessons only.
4. Select one course, then enter one or more available Week/Module numbers such as `1`, `1,3-5`, or
   `1，3～5`.

The “all current courses” operation excludes archived courses. If Ed's page structure changes and
the tool cannot safely distinguish current courses from archived ones, bulk synchronisation is
disabled and you must select courses individually. The menu stays open after each operation until
you explicitly choose `0 Exit`.

Courses without downloadable Lessons are skipped for Lesson content without preventing their
Discussions from being saved.

## Scan and synchronise

```console
# List a course's available Lesson groups without downloading files
uv run ed-downloader scan --course DEMO1001

# Incrementally synchronise one course, or only one content scope
uv run ed-downloader sync --course DEMO1001
uv run ed-downloader sync --course DEMO1001 --scope discussions
uv run ed-downloader sync --course DEMO1001 --scope lessons

# Synchronise selected Lesson groups by their displayed numbers
uv run ed-downloader sync --course DEMO1001 --scope lessons --groups "1,3-5"

# Synchronise every current course, excluding archived courses
uv run ed-downloader sync --all

# Force a full Discussions pass or re-fetch Lesson attachment bodies
uv run ed-downloader sync --course DEMO1001 --full
uv run ed-downloader sync --course DEMO1001 --scope lessons --refresh
```

A normal sync must specify exactly one `--course`; all courses are only selected by the explicit
`--all` option. Course codes and Ed numeric IDs are both accepted. `--groups` applies only to
Lessons and cannot be combined with `--all`. Use `--headed` if you need to watch the automated
browser, and `--output /another/folder` to choose a different material directory.

The default output is the current user's Desktop under `Monash ED Downloads` and has this shape:

```text
Course name/
├── Discussions/
│   └── Course name - Discussions.json
└── Lessons/
    ├── Course name - Lessons.md
    ├── Course name - Last Sync.json
    └── 01-Week or Module name/
        └── 01-Lesson name/
            ├── Lesson name.md
            └── Files/
```

The Lessons index links to each generated Lesson Markdown file. Those files use relative links for
downloaded attachments and retain source links for media, ordinary external pages, and unsupported
slide types.

## Incremental behaviour

Discussions are stored in one persistent JSON file per course. The first run, every tenth run, and a
run with `--full` inspect the complete thread list. Other runs use Ed's recent activity and known
reply counts to find new or changed threads. Existing threads, answers, and comments are merged by
ID and receive Tags showing when they were first seen, last seen, and last changed. A safety check
stops a suspiciously incomplete full scrape instead of replacing good data.

For Lesson attachments, the private SQLite state records ETag, Last-Modified, size, SHA-256, and
local path. A later sync uses remote metadata before requesting the file body:

- unchanged local files are not downloaded again;
- changed files and manually deleted local files are downloaded again;
- interrupted transfers use temporary `.part` files before an atomic rename;
- files or groups removed from Ed are recorded as `missing_remote` without deleting local copies;
- `--refresh` deliberately bypasses the unchanged check for Lesson attachments.

If an Ed-designated webpage or quiz cannot be refreshed but a previous successful copy exists, the
tool preserves that copy rather than discarding it. Each sync prints a summary of Discussion changes
and Lesson resources that were downloaded, unchanged, skipped as media, or kept as links.

During a sync, an interactive terminal shows persistent progress for course selection, Discussion
discovery, thread reading, Lesson processing, and resource checks. Stages with a known item count use
a progress bar; discovery and resource stages use an activity indicator because their final totals
are not known in advance. Redirected or non-interactive output uses plain English progress lines.

## Privacy and repository safety

The dedicated Ed browser profile, login confirmation, browser storage, and SQLite database live in
the operating system's private per-user data directory: normally
`%LOCALAPPDATA%\Monash ED Downloader\` on Windows,
`~/Library/Application Support/Monash ED Downloader/` on a Mac, and the standard user data
directory on Linux. Downloaded materials live outside the repository, and `.gitignore` excludes
common credentials, databases, partial files, and output directories. Exported URLs remove common
token and temporary-signature query parameters, and HTML login pages are not saved as attachments.

Before publishing changes, still review `git status` and do not commit course materials or login
data. Only access material that your own Monash account is authorised to use.

API Token login is planned as a separate stage after browser-based behaviour is stable. Any future
Token will use the operating system's credential store rather than the repository, material
directory, logs, or SQLite database.

## Troubleshooting

- **Login required:** run `uv run ed-downloader login`, finish SSO/MFA, confirm that an Ed course
  page is visible, return to the terminal, and press Enter.
- **Course not found or ambiguous:** run `uv run ed-downloader courses` and use the displayed course
  code or numeric Ed ID. If duplicate codes exist, use the numeric ID.
- **Bulk sync is refused:** Ed's dashboard could not be classified safely. Select one course at a
  time rather than assuming which courses are current.
- **A course has no Lessons:** this is allowed. Lesson content is skipped, while Discussions can
  still synchronise.
- **A file or page failed:** retry the sync. Completed files and previously saved page content remain
  intact, and incomplete `.part` files are not presented as complete downloads.
- **Need a clean Lesson re-fetch:** add `--refresh`; this consumes more bandwidth. Use `--full`
  separately when you need a complete Discussions pass.

## Development checks

Run these commands manually from Terminal after `uv sync --all-groups`. They use only anonymous,
offline fixtures and simulated HTTP responses; they do not sign in to Ed or download course
material.

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

## License

The source code is available under the [MIT License](LICENSE). Course material downloaded by the
tool is not covered by this software license and must not be redistributed without permission.
