{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
    in
    flake-utils.lib.eachSystem supportedSystems (
      system:
      let
        localOverlay = import ./overlay.nix;

        pkgs = import nixpkgs {
          inherit system;
          overlays = [ localOverlay ];
        };

        pythonDev = pkgs.python3.pkgs.manikin.pythonModule.withPackages (
          ps:
          with ps;
          [
            black
            isort
            mypy
            pytest
          ]
          ++ pkgs.manikin.propagatedBuildInputs
          ++ pkgs.manikin.nativeBuildInputs
        );

        mkApp = text: {
          type = "app";
          program = pkgs.lib.getExe (
            pkgs.writeShellApplication {
              name = "app";
              runtimeInputs = [
                pythonDev
                pkgs.pyright
                pkgs.just
              ];
              inherit text;
            }
          );
        };
      in
      {
        packages = {
          inherit (pkgs) manikin;
          default = pkgs.manikin;
        };

        checks = {
          python-minimum = pkgs.python312.pkgs.callPackage ./default.nix { };
          nix-cli =
            pkgs.runCommand "manikin-nix-cli-tests"
              {
                nativeBuildInputs = [ (pkgs.python3.withPackages (ps: [ ps.pytest ])) ];
                MANIKIN_NIX_EXECUTABLE = "${pkgs.manikin}/bin/manikin";
              }
              ''
                python -m pytest -c ${./pyproject.toml} ${./tests/test_nix_cli.py}
                touch "$out"
              '';
        };

        devShells = {
          default = pkgs.mkShell {
            inputsFrom = [ pkgs.manikin ];
            nativeBuildInputs = [
              pythonDev
              pkgs.pyright
              pkgs.nodejs # For missing libatomic in some environments
            ];
            packages = [ pkgs.python3.pkgs.venvShellHook ];
            venvDir = ".venv";
            postVenvCreation = ''
              # Nix supplies dependencies and setuptools; only install this worktree's code.
              python -m pip install --no-deps --no-build-isolation -e .
            '';
            shellHook = ''
              runHook venvShellHook
              export PYTHONPATH="''${PYTHONPATH:-}:."
            '';
          };
        };

        apps = {
          format = mkApp "just format";
          lint = mkApp "just lint";
        };

        formatter = pkgs.nixfmt;
      }
    );
}
