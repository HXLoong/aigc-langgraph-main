"""评测版本指纹：包含未提交代码和提示词，不只记录旧提交号。"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from app.config import get_settings

ASSERTION_VERSION = "deterministic-v2"


def execution_metadata() -> dict[str, str]:
    """按固定顺序摘要实际工作区，CLI 与平台实验共用版本口径。"""
    repository = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    # 代码与提示词都计入；字节顺序固定，避免平台路径不同导致伪版本变化。
    for root in (repository / "app", repository / "harness", repository / "scripts"):
        for path in sorted(root.rglob("*")):
            if path.suffix in {".py", ".md", ".yaml"} and path.is_file():
                digest.update(str(path.relative_to(repository)).encode())
                digest.update(path.read_bytes())
    # 部署包可能没有 Git；内容指纹仍然完整，不伪造提交号。
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository,
                                         stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unversioned"
    return {"commit": commit,
            "code_hash": digest.hexdigest(), "model": get_settings().llm_model_standard,
            "provider": get_settings().llm_provider,
            "assertion_version": ASSERTION_VERSION}
