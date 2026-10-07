{ pkgs }:
pkgs.stdenvNoCC.mkDerivation {
  pname = "agent-deck-archive-only-custodian";
  version = "1";
  dontUnpack = true;
  nativeBuildInputs = [ pkgs.makeWrapper ];
  installPhase = ''
    runHook preInstall
    mkdir -p "$out/bin" "$out/libexec"
    install -m 0444 \
      ${../../private_dot_local/bin/executable_agent-deck-archive-only-custodian} \
      "$out/libexec/agent-deck-archive-only-custodian.py"
    makeWrapper ${pkgs.python3}/bin/python3 \
      "$out/bin/agent-deck-archive-only-custodian" \
      --add-flags "$out/libexec/agent-deck-archive-only-custodian.py"
    runHook postInstall
  '';
}
