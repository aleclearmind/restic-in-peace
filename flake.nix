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
            jsonschema
          ];

          # restic-in-peace shells out to restic; make sure it's on PATH.
          nativeBuildInputs = [ pkgs.makeWrapper ];

          # Regenerate the flag-types snapshot against the exact restic this
          # flake builds against so the strict schema matches that version.
          preBuild = ''
            python scripts/generate_restic_flags.py \
              ${pkgs.restic}/bin/restic \
              restic_in_peace/restic_flags.json
          '';

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
              jsonschema
              setuptools
              pytest
              mypy
              types-pyyaml
              types-requests
            ]))
          ];
        };

        checks.default = pkgs.runCommand "rip-tests" {
          nativeBuildInputs = [
            restic-in-peace
            pkgs.restic
            (python.withPackages (ps: with ps; [
              pytest pyyaml jsonschema mypy types-pyyaml types-requests loguru requests notify2
            ]))
          ];
        } ''
          export HOME=$TMPDIR/home
          mkdir -p $HOME
          cp -r ${./restic_in_peace} ./restic_in_peace
          cp -r ${./tests} ./tests
          cp ${./pyproject.toml} ./pyproject.toml
          mypy
          pytest ./tests -v
          touch $out
        '';
      });
}
