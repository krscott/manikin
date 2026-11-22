set positional-arguments

default:
    just --list

run *args:
    manikin "$@"

test *args:
    python -m pytest "$@"

# Manual: run the pose backend on the GPU (needs the model weights).
test-gpu *args:
    python -m pytest -m gpu "$@"

# Manual: apply a pose with the Blender add-on in headless Blender.
test-blender *args:
    MANIKIN_BLENDER="$(nix build --no-link --print-out-paths --inputs-from . nixpkgs#blender)/bin/blender" \
        python -m pytest -m blender "$@"

# Rewrite tests/data/kungfu.pose.json from the GPU backend.
regenerate-pose-fixture:
    MANIKIN_UPDATE_FIXTURES=1 python -m pytest -m gpu tests/test_gpu.py

# Check that the locked CUDA torch builds are on cache.nixos-cuda.org.
check-cuda-cache:
    scripts/check-cuda-cache.sh

lint:
    python -m mypy .
    pyright

check: lint test

# Format files, or all tracked files when no files are provided.
format *files:
    #!/usr/bin/env bash
    set -euo pipefail

    declare -a files=()
    declare -a python_files=()
    declare -a nix_files=()
    declare -a shell_files=()

    if (($# == 0)); then
        mapfile -t files < <(git ls-files)
    else
        files=("$@")
    fi

    for file in "${files[@]}"; do
        if [ ! -f "$file" ]; then
            continue
        fi

        case "$file" in
            *.py)
                python_files+=("$file")
                ;;
            *.nix)
                nix_files+=("$file")
                ;;
            *.sh)
                shell_files+=("$file")
                ;;
        esac
    done

    if ((${#python_files[@]} > 0)); then
        python -m isort "${python_files[@]}"
        python -m black "${python_files[@]}"
    fi

    if ((${#nix_files[@]} > 0)) && command -v nix >/dev/null; then
        nix fmt "${nix_files[@]}"
    fi

    if ((${#shell_files[@]} > 0)) && command -v shfmt >/dev/null; then
        shfmt -w -i 4 "${shell_files[@]}"
    fi

# Format staged files for git pre-commit.
pre-commit:
    #!/usr/bin/env bash
    set -euo pipefail

    declare -a staged_files
    declare -a format_files=()
    declare -A partially_staged
    file=''

    mapfile -d '' -t staged_files < <(
        git diff --cached --name-only --diff-filter=ACMR -z
    )

    while IFS= read -r -d '' file; do
        partially_staged["$file"]=1
    done < <(git diff --name-only -z)

    for file in "${staged_files[@]}"; do
        if [[ -v partially_staged["$file"] ]]; then
            continue
        fi

        format_files+=("$file")
    done

    if ((${#format_files[@]} == 0)); then
        exit 0
    fi

    just format "${format_files[@]}"
    git add -- "${format_files[@]}"

install-hooks:
    git config core.hooksPath .githooks
