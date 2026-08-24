import subprocess
import zipfile
from pathlib import Path


def test_production_wheel_excludes_synthetic_corpus(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert all("synthetic_hr_knowledge" not in name for name in names)
    assert all(not name.startswith("tests/") for name in names)
