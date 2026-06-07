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
            pyyaml
            jsonschema
            tqdm
          ];

          # restic is needed at build time (setup.py regenerates
          # restic_flags.json against it) and at runtime (rip shells out to it).
          nativeBuildInputs = [ pkgs.makeWrapper pkgs.restic ];

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
              pyyaml
              jsonschema
              tqdm
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
              pytest pyyaml jsonschema tqdm mypy types-pyyaml types-requests loguru requests
            ]))
          ];
        } ''
          export HOME=$TMPDIR/home
          mkdir -p $HOME
          cp -r ${./restic_in_peace} ./restic_in_peace
          cp -r ${./tests} ./tests
          cp -r ${./scripts} ./scripts
          cp ${./pyproject.toml} ./pyproject.toml
          chmod -R u+w ./restic_in_peace
          mypy
          pytest ./tests -v
          touch $out
        '';
      });
}
