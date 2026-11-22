{
  buildPythonPackage,
  fetchFromGitHub,
  lib,
  setuptools,
  braceexpand,
  einops,
  numpy,
  omegaconf,
  opencv4,
  pillow,
  pytorch-lightning,
  roma,
  timm,
  torch,
  torchvision,
  yacs,
}:
buildPythonPackage {
  pname = "sam-3d-body";
  version = "1.0.0-unstable-2026-02-19";
  pyproject = true;

  src = fetchFromGitHub {
    owner = "facebookresearch";
    repo = "sam-3d-body";
    rev = "b5c765a0d89d789985e186d396315e7590887b94";
    hash = "sha256-l5tGhOeaVbyLvGnJek4Lh4VQMgw9W5OfUDPuPg0cqnw=";
  };

  # Upstream has no build metadata. Visualization needs detectron2 and pyrender,
  # which inference does not use.
  postPatch = ''
    rm -r sam_3d_body/visualization
    cat > pyproject.toml <<'TOML'
    [build-system]
    requires = ["setuptools"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "sam-3d-body"
    version = "1.0.0"

    [tool.setuptools.packages.find]
    include = ["sam_3d_body*"]
    TOML
  '';

  build-system = [ setuptools ];

  dependencies = [
    braceexpand
    einops
    numpy
    omegaconf
    opencv4
    pillow
    pytorch-lightning
    roma
    timm
    torch
    torchvision
    yacs
  ];

  pythonImportsCheck = [ "sam_3d_body" ];

  meta = {
    description = "Single-image full-body 3D human mesh recovery";
    homepage = "https://github.com/facebookresearch/sam-3d-body";
    # SAM License: royalty-free, with use restrictions (weapons, military, ITAR).
    license = lib.licenses.unfree;
  };
}
