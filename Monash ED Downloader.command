#!/bin/zsh

set -u

launcher_dir=${0:A:h}
cd "$launcher_dir" || exit 1

runtime_root="$HOME/Library/Application Support/Monash ED Downloader/runtime"
uv_install_dir="$runtime_root/uv-bin"
user_environment="$runtime_root/environment"
python_install_dir="$runtime_root/python"
uv_cache_dir="$HOME/Library/Caches/Monash ED Downloader/uv"
uv_version="0.12.13"
uv_bin="$uv_install_dir/uv"

pause_and_exit() {
    local status=$1
    print ""
    read -r "?Press Return to close..."
    exit "$status"
}

if [[ ! -x "$uv_bin" ]]; then
    if [[ ! -x /usr/bin/curl ]]; then
        print "Cannot prepare the runtime because curl was not found."
        pause_and_exit 1
    fi

    print "First launch: preparing an isolated ED Downloader environment."
    print "This downloads uv from Astral and prepares the required Python and dependencies."
    print "It does not modify the system Python, PATH, or shell configuration."
    print ""

    mkdir -p "$uv_install_dir" "$user_environment" "$python_install_dir" "$uv_cache_dir" || {
        print "Cannot create the runtime directory: $runtime_root"
        pause_and_exit 1
    }
    chmod 700 "$runtime_root" "$uv_install_dir" "$user_environment" "$python_install_dir"

    installer=$(/usr/bin/mktemp "${TMPDIR:-/tmp}/monash-ed-uv.XXXXXX") || {
        print "Cannot create the temporary installer file."
        pause_and_exit 1
    }
    trap '/bin/rm -f "$installer"' EXIT

    if ! /usr/bin/curl --proto '=https' --tlsv1.2 -LsSf \
        "https://astral.sh/uv/$uv_version/install.sh" -o "$installer"; then
        print "The runtime download failed. Check the network and try again."
        pause_and_exit 1
    fi
    if ! env UV_UNMANAGED_INSTALL="$uv_install_dir" UV_NO_MODIFY_PATH=1 \
        /bin/sh "$installer"; then
        print "The runtime installation failed. Double-click the launcher to try again."
        pause_and_exit 1
    fi
    if [[ ! -x "$uv_bin" ]]; then
        print "uv was installed, but it was not found at: $uv_bin"
        pause_and_exit 1
    fi
fi

export UV_PROJECT_ENVIRONMENT="$user_environment"
export UV_PYTHON_INSTALL_DIR="$python_install_dir"
export UV_CACHE_DIR="$uv_cache_dir"

"$uv_bin" run --managed-python --no-dev --frozen ed-downloader menu
menu_status=$?

pause_and_exit "$menu_status"
