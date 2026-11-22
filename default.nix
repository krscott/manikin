{
  buildPythonPackage,
  lib,
  pythonOlder,
  pytestCheckHook,
  numpy,
  pillow,
  python-multipart,
  sam-3d-body,
  segno,
  setproctitle,
  setuptools,
  starlette,
  torch,
  uvicorn,
  httpx,
}:
buildPythonPackage {
  name = "manikin";
  src = lib.cleanSource ./.;
  pyproject = true;
  disabled = pythonOlder "3.13";

  nativeBuildInputs = [ setuptools ];

  propagatedBuildInputs = [
    numpy
    pillow
    python-multipart
    sam-3d-body
    segno
    setproctitle
    starlette
    torch
    uvicorn
  ];

  # Isolate the CLI before Python fixup adds the packaged dependency paths.
  postInstall = ''
    sed -i '1s/$/ -I/' "$out/bin/manikin"
  '';

  nativeCheckInputs = [
    httpx
    pytestCheckHook
  ];

  # Integration tests need the installed executable; gpu and blender tests are manual.
  disabledTestMarks = [
    "integration"
    "gpu"
    "blender"
  ];

  pythonImportsCheck = [ "manikin" ];

  meta = {
    mainProgram = "manikin";
    description = "Capture a pose from a phone photo for a Blender Rigify rig";
    license = lib.licenses.agpl3Plus;
  };
}
