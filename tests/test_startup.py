import subprocess
import sys

from conftest import ROOT


def test_genai_is_not_imported_at_startup():
    """google.genai (~0.7 s) must load on the worker thread, not before the
    window appears."""
    code = "import sys, main; print('google.genai' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_lazy_proxies_build_real_objects():
    import main
    fr = main.types.FunctionResponse(id="1", name="t", response={"result": "ok"})
    assert fr.name == "t"
    cfg = main.types.LiveConnectConfig(response_modalities=["AUDIO"])
    assert cfg.response_modalities
    assert callable(main.genai.Client)
