{ config, lib, pkgs, ... }:

let
  cfg = config.services.restic-in-peace;
in {
  options.services.restic-in-peace = {
    enable = lib.mkEnableOption "the restic-in-peace backup timer";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../. {};
      defaultText = lib.literalExpression "pkgs.callPackage <restic-in-peace-source> {}";
      description = ''
        The restic-in-peace package. Override to swap in your own build
        (e.g. one from a nixpkgs overlay).
      '';
    };

    configFile = lib.mkOption {
      type = lib.types.strMatching "^/.+";
      example = "/etc/restic-in-peace/rip.yml";
      description = ''
        Absolute path to the rip.yml on the running system. Stored as a string
        on purpose — passing a Nix path here would copy the file (with its
        embedded RESTIC_PASSWORD) into the world-readable Nix store. Provision
        the file out of band (manual scp, configuration management, etc.) and
        leave it owned by root mode 0600.
      '';
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "hourly";
      example = "*-*-* 03:00:00";
      description = ''
        systemd OnCalendar expression. The orchestrator runs at this cadence;
        the per-run frequency gate inside rip.yml decides whether any
        individual profile actually gets re-backed up.
      '';
    };

    name = lib.mkOption {
      type = lib.types.str;
      default = "rip-backup";
      description = "Basename of the systemd unit pair (service + timer).";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services."${cfg.name}" = {
      description = "restic-in-peace backup orchestrator";
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${cfg.package}/bin/rip --config ${cfg.configFile} backup";
        User = "root";
      };
    };

    systemd.timers."${cfg.name}" = {
      description = "Scheduled restic-in-peace backups";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.schedule;
        Persistent = true;
        RandomizedDelaySec = "10m";
        Unit = "${cfg.name}.service";
      };
    };
  };
}
