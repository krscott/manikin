final: prev: {
  python3 = prev.python3.override {
    packageOverrides = pyFinal: _: {
      sam-3d-body = pyFinal.callPackage ./nix/sam-3d-body.nix { };
      manikin = pyFinal.callPackage ./default.nix { };
    };
  };

  python3Packages = final.python3.pkgs;

  manikin = prev.python3.pkgs.toPythonApplication final.python3.pkgs.manikin;
}
