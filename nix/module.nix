self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.manikin;
  settingsFormat = pkgs.formats.toml { };
  configFile = settingsFormat.generate "manikin.toml" cfg.settings;
in
{
  options.services.manikin = {
    enable = lib.mkEnableOption "manikin, which turns phone photos into Rigify poses";

    package = lib.mkOption {
      type = lib.types.package;
      # manikin's own build keeps CUDA torch on cache.nixos-cuda.org; rebuilding
      # it against this system's nixpkgs would compile torch locally.
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.manikin;
      defaultText = lib.literalExpression "manikin.packages.\${system}.manikin";
      description = "The manikin package.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      description = ''
        User to run as. Saved poses and model weights default to this user's
        home directory, where a Flatpak Blender can read them.
      '';
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the port on the `tailscale0` interface only.";
    };

    settings = lib.mkOption {
      type = lib.types.submodule {
        freeformType = settingsFormat.type;
        options.port = lib.mkOption {
          type = lib.types.port;
          default = 8471;
          description = "Port to listen on.";
        };
      };
      default = { };
      example = {
        out_dir = "/home/alice/blender/poses";
        model_idle_timeout = 300;
      };
      description = ''
        manikin settings, written to a TOML config file. See the README for the
        available settings. Without `host`, manikin listens on this machine's
        tailnet IPv4 address.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.manikin = {
      description = "manikin pose capture";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [
        "network-online.target"
        "tailscaled.service"
      ];
      # Finds the tailnet address with `tailscale status`.
      path = [ config.services.tailscale.package ];
      serviceConfig = {
        User = cfg.user;
        ExecStart = "${lib.getExe cfg.package} --config ${configFile} serve";
        # Tailscale may not have an address yet at boot.
        Restart = "on-failure";
        RestartSec = 10;
      };
    };

    networking.firewall.interfaces.tailscale0.allowedTCPPorts = lib.mkIf cfg.openFirewall [
      cfg.settings.port
    ];
  };
}
