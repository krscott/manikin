{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      # CUDA builds come from cache.nixos-cuda.org; see AGENTS.md before changing
      # the system, nixpkgs config, or Python versions.
      system = "x86_64-linux";

      pkgs = import nixpkgs {
        inherit system;
        overlays = [ (import ./overlay.nix) ];
        config = {
          allowUnfree = true;
          cudaSupport = true;
        };
      };

      # Packages that must not be built with CUDA, to stay on cache.nixos.org.
      plainPkgs = nixpkgs.legacyPackages.${system};

      pythonMinimum = pkgs.python313.override {
        packageOverrides = pyFinal: _: {
          sam-3d-body = pyFinal.callPackage ./nix/sam-3d-body.nix { };
        };
      };

      pythonDev = pkgs.python3.pkgs.manikin.pythonModule.withPackages (
        ps:
        with ps;
        [
          black
          httpx
          isort
          mypy
          pytest
        ]
        ++ pkgs.python3.pkgs.manikin.propagatedBuildInputs
        ++ pkgs.python3.pkgs.manikin.nativeBuildInputs
      );

      # Formatting needs no runtime dependencies, so CI avoids downloading CUDA.
      pythonFormat = plainPkgs.python3.withPackages (ps: [
        ps.black
        ps.isort
      ]);
    in
    {
      packages.${system} = {
        inherit (pkgs) manikin;
        default = pkgs.manikin;
      };

      # Store paths `just check-cuda-cache` expects on cache.nixos-cuda.org.
      legacyPackages.${system}.cudaCachePaths = {
        torch = pkgs.python3.pkgs.torch;
        torchvision = pkgs.python3.pkgs.torchvision;
        torch-minimum = pythonMinimum.pkgs.torch;
        torchvision-minimum = pythonMinimum.pkgs.torchvision;
      };

      nixosModules.default = import ./nix/module.nix self;

      checks.${system} = {
        python-minimum = pythonMinimum.pkgs.callPackage ./default.nix { };
        module =
          let
            nixos = nixpkgs.lib.nixosSystem {
              inherit system;
              modules = [
                self.nixosModules.default
                {
                  services.manikin = {
                    enable = true;
                    user = "alice";
                    openFirewall = true;
                    settings.port = 9000;
                  };
                  boot.loader.grub.enable = false;
                  fileSystems."/" = {
                    device = "nodev";
                    fsType = "tmpfs";
                  };
                  system.stateVersion = nixpkgs.lib.trivial.release;
                }
              ];
            };
            unit = nixos.config.systemd.units."manikin.service".unit;
            config = nixos.config.environment.etc."manikin/config.toml".source;
            ports = nixos.config.networking.firewall.interfaces.tailscale0.allowedTCPPorts;
          in
          assert ports == [ 9000 ];
          pkgs.runCommand "manikin-module-check" { } ''
            grep -q 'ExecStart=.*/bin/manikin --config /etc/manikin/config.toml serve' ${unit}/manikin.service
            grep -q 'User=alice' ${unit}/manikin.service
            grep -q 'RestartPreventExitStatus=2 3' ${unit}/manikin.service
            grep -q 'port = 9000' ${config}
            touch "$out"
          '';
        nix-cli =
          pkgs.runCommand "manikin-nix-cli-tests"
            {
              nativeBuildInputs = [ (plainPkgs.python3.withPackages (ps: [ ps.pytest ])) ];
              MANIKIN_NIX_EXECUTABLE = "${pkgs.manikin}/bin/manikin";
            }
            ''
              python -m pytest -c ${./pyproject.toml} ${./tests/test_nix_cli.py}
              touch "$out"
            '';
      };

      devShells.${system}.default = pkgs.mkShell {
        inputsFrom = [ pkgs.python3.pkgs.manikin ];
        nativeBuildInputs = [
          pythonDev
          pkgs.pyright
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

      apps.${system} = {
        format = {
          type = "app";
          program = pkgs.lib.getExe (
            pkgs.writeShellApplication {
              name = "format";
              runtimeInputs = [
                pythonFormat
                pkgs.just
              ];
              text = "just format";
            }
          );
        };
      };

      formatter.${system} = pkgs.nixfmt;
    };
}
