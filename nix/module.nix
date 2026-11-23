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
      description = "Open the port on the Tailscale interface only.";
    };

    settings = lib.mkOption {
      type = lib.types.submodule {
        freeformType = settingsFormat.type;
        options.port = lib.mkOption {
          type = lib.types.ints.between 1 65535;
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
    # Shared with the CLI: `manikin --config /etc/manikin/config.toml url`.
    environment.etc."manikin/config.toml".source = configFile;
    environment.systemPackages = [ cfg.package ];

    systemd.services.manikin = {
      description = "manikin pose capture";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      restartTriggers = [ configFile ];
      after = [
        "network-online.target"
        "tailscaled.service"
      ];
      # Finds the tailnet address with `tailscale status`.
      path = [ config.services.tailscale.package ];
      serviceConfig = {
        User = cfg.user;
        ExecStart = "${lib.getExe cfg.package} --config /etc/manikin/config.toml serve";
        # Tailscale may not have an address yet at boot (exit 1). Bad settings
        # (2) and missing model weights (3) need a person, so don't retry those.
        Restart = "on-failure";
        RestartSec = 10;
        RestartPreventExitStatus = "2 3";
      };
    };

    networking.firewall.interfaces.${config.services.tailscale.interfaceName}.allowedTCPPorts =
      lib.mkIf cfg.openFirewall
        [ cfg.settings.port ];
  };
}
