"""PyInstaller用のエントリポイント。svtracker.cli:main をそのまま呼ぶだけ。"""
from svtracker.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
