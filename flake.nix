{
  description = "restic-in-peace (rip): a wrapper around resticprofile / restic";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;

        # nixpkgs 26.05 ships resticprofile 0.31.0, whose TestDurationDecoder
        # asserts a specific Go stdlib error string that changed in newer Go
        # releases. Skip just that test rather than disabling the whole suite.
        resticprofile = pkgs.resticprofile.overrideAttrs (old: {
          checkFlags = (old.checkFlags or []) ++ [ "-skip=^TestDurationDecoder$" ];
        });

        restic-in-peace = python.pkgs.buildPythonApplication {
          pname = "restic-in-peace";
          version = "0.1.0";
          src = ./.;
          format = "setuptools";

          propagatedBuildInputs = with python.pkgs; [
            loguru
            requests
            notify2
          ];

          # restic-in-peace shells out to restic; make sure it's on PATH.
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postFixup = ''
            wrapProgram $out/bin/restic-in-peace \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.restic ]}
          '';

          doCheck = false;

          meta = with pkgs.lib; {
            description = "Restic wrapper implementing missing features needed by rev.ng";
            homepage = "https://rev.ng/gitlab/fcremo/restic-in-peace";
            mainProgram = "restic-in-peace";
            platforms = platforms.unix;
          };
        };

        # resticprofile has no CLI flag to override the restic binary (only a
        # config-file setting), so we expose restic-in-peace under the name
        # `restic` via a shim directory and put it first on PATH.
        # Chain at runtime: resticprofile -> restic-in-peace -> restic.
        restic-shim = pkgs.runCommand "restic-shim" {} ''
          mkdir -p $out/bin
          ln -s ${restic-in-peace}/bin/restic-in-peace $out/bin/restic
        '';

        resticprofile-rip = pkgs.symlinkJoin {
          name = "resticprofile-rip-${resticprofile.version}";
          paths = [ resticprofile ];
          nativeBuildInputs = [ pkgs.makeWrapper ];
          postBuild = ''
            wrapProgram $out/bin/resticprofile \
              --prefix PATH : ${restic-shim}/bin
          '';
          meta = resticprofile.meta // {
            description = "resticprofile wrapped to use restic-in-peace as its restic binary";
            mainProgram = "resticprofile";
          };
        };
      in {
        packages = {
          default = resticprofile-rip;
          restic-in-peace = restic-in-peace;
          resticprofile-rip = resticprofile-rip;
        };

        apps.default = {
          type = "app";
          program = "${resticprofile-rip}/bin/resticprofile";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            resticprofile-rip
            restic-in-peace
            pkgs.restic
            (python.withPackages (ps: with ps; [
              loguru
              requests
              notify2
              setuptools
              pytest
            ]))
          ];
        };

        checks.default = pkgs.runCommand "rip-tests" {
          nativeBuildInputs = [
            restic-in-peace
            resticprofile
            pkgs.restic
            (python.withPackages (ps: [ ps.pytest ]))
          ];
        } ''
          export HOME=$TMPDIR/home
          mkdir -p $HOME
          cp -r ${./tests} ./tests
          pytest ./tests -v
          touch $out
        '';
      });
}
