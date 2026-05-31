{
  description = "restic-in-peace (rip): a restic wrapper with profile support";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;

        restic-in-peace = python.pkgs.buildPythonApplication {
          pname = "restic-in-peace";
          version = "0.1.0";
          src = ./.;
          format = "setuptools";

          propagatedBuildInputs = with python.pkgs; [
            loguru
            requests
            notify2
            pyyaml
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
      in {
        packages = {
          default = restic-in-peace;
          restic-in-peace = restic-in-peace;
        };

        apps.default = {
          type = "app";
          program = "${restic-in-peace}/bin/restic-in-peace";
        };

        devShells.default = pkgs.mkShell {
          packages = [
            restic-in-peace
            pkgs.restic
            (python.withPackages (ps: with ps; [
              loguru
              requests
              notify2
              pyyaml
              setuptools
              pytest
            ]))
          ];
        };

        checks.default = pkgs.runCommand "rip-tests" {
          nativeBuildInputs = [
            restic-in-peace
            pkgs.restic
            (python.withPackages (ps: [ ps.pytest ps.pyyaml ]))
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
