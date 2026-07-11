import sys
import types

import svtracker
from svtracker import version


def test_full_version_marks_dev_when_no_build_info(monkeypatch):
    monkeypatch.delitem(sys.modules, "svtracker._build_info", raising=False)
    monkeypatch.delattr(svtracker, "_build_info", raising=False)

    result = version.full_version()

    assert svtracker.__version__ in result
    assert "開発版" in result


def test_full_version_includes_build_info_when_present(monkeypatch):
    build_info = types.ModuleType("svtracker._build_info")
    build_info.GIT_SHA = "abcdef1234567890"
    build_info.BUILD_DATE = "2026-07-11 12:34 UTC"
    monkeypatch.setitem(sys.modules, "svtracker._build_info", build_info)
    monkeypatch.setattr(svtracker, "_build_info", build_info, raising=False)

    result = version.full_version()

    assert svtracker.__version__ in result
    assert "abcdef1" in result
    assert "2026-07-11 12:34 UTC" in result
    assert "開発版" not in result
