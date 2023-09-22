#!/bin/bash

echo "args: $*"

# Set the default arguments
git_home_dir=~/.rmake/githome
src_dir=
dst_dir=
commands=
make_vars=
exec_cmd_args=
rsync_args="-av --delete --mkpath --exclude=".git""
force=0
git_origin=origin

# internal variables
has_include_from=0
has_exclude_from=0
is_sources_synced=0

# Retrieve the workspace root directory
workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dir="$workspace_dir"
while true; do
    # Check if the file exists in the current directory
    if [[ -f "$dir/.rmake-user.sh" || -f "$dir/.rmake-excludes" || -f "$dir/.rmake-includes" || -d "$dir/.git" ]]; then
        workspace_dir=$dir
    fi
    # Get the parent directory
    parent="$(dirname "$dir")"
    # Check if we've reached the root directory
    if [ "$parent" == "$dir" ]; then
        break
    fi
    dir="$parent"
done
unset dir parent

# Quote the command arguments as needed
function quote() {
    declare -a params
    for param; do
        if [[ -z "${param}" || "${param}" =~ [^A-Za-z0-9_@%+=:,./-] ]]; then
            params+=("'${param//\'/\'\"\'\"\'}'")
        else
            params+=("${param}")
        fi
    done
    echo "${params[*]}"
}

# Include the user script if it exists
if [[ -f "$workspace_dir/.rmake-user.sh" ]]; then
    source "$workspace_dir/.rmake-user.sh"
else
    # sync_outputs() -> int
    # Synchronize build output files from <dst_dir> into <src_dir>.
    # Return 0 for success, others for failure.
    sync_outputs() {
        return 0
    }

    # user_parse_args(args:[string]) -> int
    # Return the number of parsed arguments, 0 for failure.
    user_parse_args() {
        return 0
    }

    # user_exec(command:string) -> int
    # Return 0 for success, others for failure.
    user_exec() {
        echo "Error: Unknown command: $1" >&2
        return 0
    }
fi

# Loop through the command-line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --src-dir)
            if [[ -n "$2" && "$2" != "-"* ]]; then
                src_dir="$2"
                shift 2
            else
                echo "Error: $1 requires an argument." >&2
                exit 1
            fi
            ;;
        --dst-dir)
            if [[ -n "$2" && "$2" != "-"* ]]; then
                dst_dir="$2"
                shift 2
            else
                echo "Error: $1 requires an argument." >&2
                exit 1
            fi
            ;;
        --include|--include-from|--exclude|--exclude-from)
            if [[ -n "$2" && "$2" != "-"* ]]; then
                rsync_args="$rsync_args $1="$2""
                if [[ $1 == "--include-from" ]]; then
                    has_include_from=1
                elif [[ $1 == "--exclude-from" ]]; then
                    has_exclude_from=1
                fi
                shift 2
            else
                echo "Error: $1 requires an argument." >&2
                exit 1
            fi
            ;;
        --progress|--no-perms)
            rsync_args="$rsync_args "$1""
            ;;
        -f|--force)
            force=1
			shift 1
            ;;
        --git-origin)
            if [[ -n "$2" && "$2" != "-"* ]]; then
                git_origin="$2"
                shift 2
            else
                echo "Error: $1 requires an argument." >&2
                exit 1
            fi
            ;;
        -*)
            user_parse_args "$*"
            parsed=$?
            if [[ $parsed -le 0 ]]; then
                echo "Error: Unknown argument: $1" >&2
                exit 1
            fi
            shift $parsed
            ;;
        exec|rsync-exec)
            commands="$commands $1"
            shift 1
            exec_cmd_args="$*"
            shift $#
            ;;
        *"="*)
            make_vars="$make_vars "$1""
            shift 1
            ;;
        *)
            commands="$commands $1"
            shift 1
            ;;
    esac
done

# Define a function for substring replacement
replace_substr_and_before() {
    local original="$1"
    local substring="$2"
    local replacement="$3"

    # Find the position of the substring
    local prefix="${original%%$substring*}"
    local position="${#prefix}"

    # Check if the substring exists in the string
    if [ $position -lt ${#original} ]; then
        # Extract the part of the string after the substring
        local after="${original:position+${#substring}}"

        # Replace the original string with the replacement string and the part after the substring
        echo "${replacement}${after}"
        return 0
    else
        return 1
    fi
}

# Define a function for "<condition> ? <true_value> : <false_value>"
if3() {
    local condition="$1"
    local true_value="$2"
    local false_value="$3"

    if [ "$condition" -eq 0 ]; then
        echo $false_value
    else
        echo $true_value
    fi
}

# Clone repository, checkout the current branch,
# and change the working directory to the cloned repository.
git_try_clone() {
    if [[ ! -d "$dst_dir" ]]; then
        cd "$src_dir" || return $?
        # Get the current repository URL
        local url="$(git config --get remote.$git_origin.url)" || return $?
        # Get the current branch name
        local branch="$(git rev-parse --abbrev-ref HEAD)" || return $?
        local branch_opt=
        # Check if the remote branch exists.
        if git ls-remote --exit-code --heads $git_origin "$branch" >/dev/null 2>&1; then
            branch_opt="-b "$branch""
        fi

        mkdir -p "$(dirname "$dst_dir")" && \
            git clone $branch_opt $url "$dst_dir" && \
            cd "$dst_dir" && \
            git submodule update --init --recursive || \
            return $?
    fi
    cd "$dst_dir"
    return $?
}

# Checkout the current branch
git_checkout() {
    local force="$1"

    git_try_clone || return $?

    pushd "$src_dir" >/dev/null || return $?
    # Get the current repository URL
    local url="$(git config --get remote.$git_origin.url)" || return $?
    # Get the current branch name
    local branch="$(git rev-parse --abbrev-ref HEAD)" || return $?
    popd >/dev/null || return $?

    local current_branch="$(git rev-parse --abbrev-ref HEAD)" || return $?
    if [[ "$current_branch" != "$branch" || $force -eq 1 ]]; then
        git remote update || return $?
        if git branch | grep -e "^\\*\\?\\s*$branch\$" >/dev/null; then
            git checkout $(if3 $force -f) "$branch" || return $?
        elif git ls-remote --exit-code --heads $git_origin "$branch" >/dev/null 2>&1; then
            # The remote branch exists
            git checkout $(if3 $force -f) -b "$branch" "$git_origin/$branch" || return $?
        fi
        git pull || return $?
        git submodule update --init --recursive || return $?
    fi
    return 0
}

# Sync source files to the destination directory
sync_sources() {
    if [[ $is_sources_synced -eq 0 ]]; then
        git_try_clone || return $?
        is_sources_synced=1
        rsync $rsync_args "$src_dir/" "$dst_dir/"
        return $?
    fi
    return 0
}

# Set the default arguments after parsing the command-line
# <src_dir>
test -z "$src_dir" && src_dir="$workspace_dir"
# <dst_dir>
test -z "$dst_dir" && dst_dir="$(replace_substr_and_before \
    "$src_dir" "/$(basename $git_home_dir)/" "$git_home_dir/")" || {\
        echo "Error: \"$src_dir\" does not have an ancestor directory named \"$(basename $git_home_dir)\"" >&2
        echo "Please specify the destination directory with the option: --dst-dir <xxx>"
        exit $?
    }
# <rsync_args>
test $has_include_from -eq 0 && {
    if [[ -f "$src_dir/.rmake-includes" ]]; then
        rsync_args="$rsync_args --include-from="$src_dir/.rmake-includes""
    fi
}
test $has_exclude_from -eq 0 && {
    rsync_exclude_from="$src_dir/.rmake-excludes"
    if [[ -f "$src_dir/.rmake-excludes" ]]; then
        rsync_args="$rsync_args --exclude-from="$src_dir/.rmake-excludes""
    elif [[ -f "$src_dir/.gitignore" ]]; then
        rsync_args="$rsync_args --exclude-from="$src_dir/.gitignore""
    fi
}
# <commands>
test -z "$commands" && commands=build

if [[ ! -d "$src_dir" ]]; then
    echo "Error: $src_dir is not a directory." >&2
    exit 1
fi

echo "rsync: [ $src_dir ] ==> [ $dst_dir ] "

# Execute all commands
for command in $commands; do
    case "$command" in
        clone|pull)
            git_checkout 1 || exit $?
            ;;
        checkout)
            git_checkout $force || exit $?
            ;;
        remove-git)
            cd ~ && rm -rf "$dst_dir" || exit $?
            ;;
        exec)
            test -d "$dst_dir" && cd "$dst_dir"
            $exec_cmd_args || exit $?
            ;;
        rsync-exec)
            sync_sources && $exec_cmd_args || exit $?
            ;;
        cargo|cargo-*|clean|clean-*|cmake|cmake-*)
            sync_sources && make $command $make_vars || exit $?
            ;;
        *)
            user_exec "$command" || exit $?
            ;;
    esac
done
exit 0
