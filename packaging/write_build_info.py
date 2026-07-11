"""CIビルド時にコミットSHA・ビルド日時を svtracker/_build_info.py に書き込む.

pip install / PyInstaller の前に実行すること(パッケージに焼き込まれる)。
GITHUB_SHA が無いローカル実行では git から取得を試み、それも無ければ unknown。
"""
from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path


def resolve_git_sha() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001 - gitが無い/リポジトリ外なら unknown でよい
        return "unknown"


def main() -> None:
    sha = resolve_git_sha()
    build_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    dest = Path(__file__).resolve().parents[1] / "src" / "svtracker" / "_build_info.py"
    dest.write_text(
        f'"""CIビルド時に packaging/write_build_info.py が生成するファイル(コミット対象外)."""\n'
        f'GIT_SHA = "{sha}"\n'
        f'BUILD_DATE = "{build_date}"\n',
        encoding="utf-8",
    )
    print(f"wrote {dest}: {sha[:7]} {build_date}")


if __name__ == "__main__":
    main()
