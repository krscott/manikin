#!/usr/bin/env bash
# Check that the locked CUDA torch builds are on cache.nixos-cuda.org.
# Run before accepting a flake.lock update: a miss means compiling torch locally.
set -euo pipefail

cache=https://cache.nixos-cuda.org
cd "$(dirname "$0")/.."

mapfile -t paths < <(
    nix eval --raw .#legacyPackages.x86_64-linux.cudaCachePaths --apply '
        ps: builtins.concatStringsSep "\n"
          (builtins.attrValues (builtins.mapAttrs (n: p: "${n} ${p.outPath}") ps))
    '
)

missing=0
for entry in "${paths[@]}"; do
    name=${entry%% *}
    path=${entry#* }
    if nix path-info --store "$cache" "$path" >/dev/null 2>&1; then
        echo "cached:  $name $path"
    else
        echo "MISSING: $name $path"
        missing=1
    fi
done

if ((missing)); then
    echo "Some CUDA builds are not on $cache; keep the previous flake.lock." >&2
    exit 1
fi
