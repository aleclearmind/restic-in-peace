{ lib, python3, makeWrapper, restic }:

python3.pkgs.buildPythonApplication {
  pname = "restic-in-peace";
  version = "0.1.0";
  src = lib.cleanSource ../.;
  format = "setuptools";

  propagatedBuildInputs = with python3.pkgs; [
    requests
    pyyaml
    jsonschema
    tqdm
  ];

  # restic is needed at build time (setup.py regenerates restic_flags.json
  # against it) and at runtime (rip shells out to it).
  nativeBuildInputs = [ makeWrapper restic ];

  postFixup = ''
    wrapProgram $out/bin/rip \
      --prefix PATH : ${lib.makeBinPath [ restic ]}
  '';

  doCheck = false;

  meta = with lib; {
    description = "Restic wrapper implementing missing features needed by rev.ng";
    homepage = "https://github.com/aleclearmind/restic-in-peace";
    mainProgram = "rip";
    platforms = platforms.unix;
  };
}
