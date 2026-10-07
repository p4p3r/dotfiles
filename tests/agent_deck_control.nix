{ publicFlake }:
let
  public = builtins.getFlake publicFlake;
  pkgs = public.inputs.nixpkgs.legacyPackages.x86_64-linux;
  evaluate =
    enabled: overrides:
    (public.inputs.home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        ../nix/modules/agent-deck-control.nix
        {
          home.username = "fixture";
          home.homeDirectory = "/tmp/control-fixture";
          home.stateVersion = "24.05";
          programs.agent-deck-control = {
            enable = enabled;
            profileName = "fixture";
            conductorName = "controller";
            agentDeckExecutable = "/opt/fixture/agent-deck";
          }
          // overrides;
        }
      ];
    }).config;
  enabled = evaluate true { };
  disabled = evaluate false { };
  unit = "agent-deck-conductor-tick-fixture-controller";
  packages =
    config: builtins.filter (p: (p.pname or "") == "agent-deck-control-runtime") config.home.packages;
  runtime = builtins.head (packages enabled);
  valid =
    overrides: (builtins.tryEval ((evaluate true overrides).home.activationPackage.drvPath)).success;
in
assert packages disabled == [ ];
assert !(builtins.hasAttr unit disabled.systemd.user.services);
assert !(builtins.hasAttr unit disabled.systemd.user.timers);
assert !valid { profileName = "invalid/name"; };
assert !valid { conductorName = "invalid name"; };
assert !valid { registryState = "relative/registry.json"; };
assert !valid { agentDeckExecutable = "relative/agent-deck"; };
{
  inherit evaluate;
  inherit runtime;
  facts = {
    service = enabled.systemd.user.services.${unit};
    timer = enabled.systemd.user.timers.${unit};
    registryState = enabled.programs.agent-deck-control.registryState;
    packageCount = builtins.length (packages enabled);
  };
  render = pkgs.runCommand "agent-deck-control-render" { } ''
    mkdir -p "$out"
    cp ${enabled.xdg.configFile."systemd/user/${unit}.service".source} "$out/${unit}.service"
    cp ${enabled.xdg.configFile."systemd/user/${unit}.timer".source} "$out/${unit}.timer"
  '';
}
