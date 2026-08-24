from pathlib import Path


def test_production_code_and_configuration_never_reference_synthetic_fixture_path() -> None:
    roots = (Path("src"), Path("knowledge_sources"), Path("docker-compose.postgres-test.yml"))
    forbidden = "synthetic_hr_knowledge"
    for root in roots:
        paths = root.rglob("*") if root.is_dir() else (root,)
        for path in paths:
            if path.is_file():
                assert forbidden not in path.read_text(encoding="utf-8", errors="ignore")


def test_production_knowledge_source_boundary_remains_empty() -> None:
    files = tuple(path for path in Path("knowledge_sources").rglob("*") if path.is_file())
    assert files == (Path("knowledge_sources/README.md"),)
