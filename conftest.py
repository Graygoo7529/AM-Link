"""Keep default test artifacts in a unique, ignored workspace directory."""
from uuid import uuid4


def pytest_configure(config):
    # Respect an explicit --basetemp. Unique default runs avoid concurrent
    # cleanup and Windows ACLs left by a different test process.
    if config.option.basetemp is None:
        root = config.rootpath / "amlink" / "data" / "pytest-tmp"
        root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(root / ("run-" + uuid4().hex))
