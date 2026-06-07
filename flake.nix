{
  description = "restic-in-peace (rip): a restic wrapper with profile support";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      perSystem = flake-utils.lib.eachDefaultSystem (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3;
          restic-in-peace = pkgs.callPackage ./nix/package.nix {};
        in {
          packages = {
            default = restic-in-peace;
            restic-in-peace = restic-in-peace;
          };

          apps.default = {
            type = "app";
            program = "${restic-in-peace}/bin/rip";
          };

          devShells.default = pkgs.mkShell {
            packages = [
              restic-in-peace
              pkgs.restic
              pkgs.systemd  # provides systemd-analyze for unit-file tests
              (python.withPackages (ps: with ps; [
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
              pkgs.systemd
              (python.withPackages (ps: with ps; [
                pytest pyyaml jsonschema tqdm mypy types-pyyaml types-requests requests
              ]))
            ];
          } ''
            export HOME=$TMPDIR/home
            mkdir -p $HOME
            cp -r ${./restic_in_peace} ./restic_in_peace
            cp -r ${./tests} ./tests
            cp -r ${./scripts} ./scripts
            cp ${./pyproject.toml} ./pyproject.toml
            cp ${./README.md} ./README.md
            chmod -R u+w ./restic_in_peace
            mypy
            pytest ./tests -v
            touch $out
          '';
        });
    in
      perSystem // {
        # NixOS module (system-independent). Importable either as a flake
        # output or directly from the source tree via
        # `imports = [ "${fetchTarball ...}/nix/module.nix" ]`.
        nixosModules.default = import ./nix/module.nix;
      };
}
