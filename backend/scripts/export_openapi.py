"""OpenAPI 契约快照导出/校验（EDP-007）。

用法（在 backend/ 下）：
    uv run python scripts/export_openapi.py          # 生成 contracts/openapi.json + openapi.sha256
    uv run python scripts/export_openapi.py --check  # 校验快照与当前 app 定义一致，不一致 exit 1
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = BACKEND_ROOT.parent / "contracts"
OPENAPI_PATH = CONTRACTS_DIR / "openapi.json"
FINGERPRINT_PATH = CONTRACTS_DIR / "openapi.sha256"


def render_openapi() -> str:
    from edp_api.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def write_snapshot(content: str) -> None:
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(content, encoding="utf-8", newline="\n")
    FINGERPRINT_PATH.write_text(digest_of(content) + "\n", encoding="utf-8", newline="\n")


def check_snapshot(content: str) -> bool:
    if not OPENAPI_PATH.exists() or not FINGERPRINT_PATH.exists():
        return False
    if OPENAPI_PATH.read_text(encoding="utf-8") != content:
        return False
    return FINGERPRINT_PATH.read_text(encoding="utf-8").strip() == digest_of(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="导出/校验 OpenAPI 契约快照")
    parser.add_argument("--check", action="store_true", help="校验快照一致，不符 exit 1")
    args = parser.parse_args()

    content = render_openapi()
    if args.check:
        if check_snapshot(content):
            print("contract snapshot OK: contracts/openapi.json 与当前 OpenAPI 定义一致")
            return 0
        print(
            "contract snapshot DRIFT: contracts/openapi.json 与当前 OpenAPI 定义不一致，"
            "请运行 uv run python scripts/export_openapi.py 重新导出并提交",
            file=sys.stderr,
        )
        return 1

    write_snapshot(content)
    print(f"wrote {OPENAPI_PATH}")
    print(f"wrote {FINGERPRINT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
