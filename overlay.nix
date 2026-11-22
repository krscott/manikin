final: prev: {
  python3 = prev.python3.override {
    packageOverrides = _: _: {
      manikin = prev.python3.pkgs.callPackage ./default.nix { };
    };
  };

  python3Packages = final.python3.pkgs;

  manikin = prev.python3.pkgs.toPythonApplication final.python3.pkgs.manikin;
}
