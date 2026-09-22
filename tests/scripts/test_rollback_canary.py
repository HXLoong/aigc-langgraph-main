"""scripts/rollback_canary.sh · 应急回切脚本集成测试。

测试范围：参数校验、dry-run 隔离、.env 改写正确性、audit log 内容。
不测：交互式 read（需 expect/pty）—— 所有 case 都用 -y 关掉交互。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rollback_canary.sh"


def _bash_executable() -> str:
    """优先使用 Git Bash，避免 Windows 的 WSL 启动器抢占 bash 命令。"""
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            git_root = Path(git).resolve().parent.parent
            for relative_path in ("bin/bash.exe", "usr/bin/bash.exe"):
                candidate = git_root / relative_path
                if candidate.is_file():
                    return str(candidate)
    return shutil.which("bash") or "bash"


def _make_env(tmp_path: Path, canary_value: str) -> Path:
    """造一个最小 .env 模拟现场环境。"""
    env = tmp_path / ".env"
    env.write_text(
        f"""# minimal env for rollback test
QWEN_API_KEY=sk-fake
CANARY_ROOM_IDS={canary_value}
SOMETHING_ELSE=preserved
""",
        encoding="utf-8",
    )
    return env


def _run_rollback(
    workdir: Path, *extra_args: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """在指定 workdir 跑脚本（PROJECT_DIR 是脚本相对父目录推断的——
    所以测试需要把脚本的 .env 路径锚定到 workdir）。

    简化：跳过 PROJECT_DIR 推断 —— 直接把整个 scripts/rollback_canary.sh
    复制到 workdir/scripts/ 让脚本认为自己住在 workdir 下。
    """
    target_scripts = workdir / "scripts"
    target_scripts.mkdir(exist_ok=True)
    shutil.copy(SCRIPT, target_scripts / "rollback_canary.sh")
    os.chmod(target_scripts / "rollback_canary.sh", 0o755)

    full_env = {
        **os.environ,
        "PYTHON_BIN": Path(sys.executable).as_posix(),
        **(env_extra or {}),
    }
    return subprocess.run(
        [_bash_executable(), "scripts/rollback_canary.sh", *extra_args],
        cwd=workdir,
        env=full_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )


# ============================================================
# 参数校验
# ============================================================


def test_missing_reason_exits_1(tmp_path: Path) -> None:
    _make_env(tmp_path, "r1,r2")
    r = _run_rollback(tmp_path)  # 不带 --reason
    assert r.returncode == 1
    assert "--reason" in r.stdout + r.stderr


def test_help_prints_usage(tmp_path: Path) -> None:
    _make_env(tmp_path, "r1,r2")
    r = _run_rollback(tmp_path, "--help")
    assert r.returncode == 0
    assert "灰度上线" in r.stdout
    assert "--reason" in r.stdout


# ============================================================
# 前置失败：.env 不存在 / CANARY 已空
# ============================================================


def test_env_missing_aborts(tmp_path: Path) -> None:
    # 不建 .env
    r = _run_rollback(tmp_path, "--reason", "test", "-y")
    assert r.returncode == 1
    assert ".env 不存在" in r.stdout + r.stderr


def test_canary_already_empty_exits_1(tmp_path: Path) -> None:
    _make_env(tmp_path, "")  # 已空
    r = _run_rollback(tmp_path, "--reason", "test", "-y")
    assert r.returncode == 1
    assert "已为空" in r.stdout + r.stderr


# ============================================================
# dry-run · 不改文件
# ============================================================


def test_dry_run_does_not_modify_env(tmp_path: Path) -> None:
    env = _make_env(tmp_path, "r1,r2,r3")
    original = env.read_text(encoding="utf-8")
    r = _run_rollback(
        tmp_path,
        "--reason",
        "演练",
        "--dry-run",
        "--skip-wait",
        "-y",
        "--metrics-url",
        "http://127.0.0.1:1/nope",  # 故意不可达
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert env.read_text(encoding="utf-8") == original
    # audit log 也不应被创建
    assert not (tmp_path / ".rollback-audit.log").exists()


def test_dry_run_does_not_create_backup(tmp_path: Path) -> None:
    _make_env(tmp_path, "r1")
    _run_rollback(
        tmp_path,
        "--reason",
        "test",
        "--dry-run",
        "--skip-wait",
        "-y",
        "--metrics-url",
        "http://127.0.0.1:1/nope",
    )
    backups = list(tmp_path.glob(".env.rollback-*"))
    assert backups == []


# ============================================================
# 真跑：.env 改写 + audit log + 备份
# ============================================================


def test_real_run_disables_canary_and_writes_audit(tmp_path: Path) -> None:
    env = _make_env(tmp_path, "r-test-1,r-test-2")

    r = _run_rollback(
        tmp_path,
        "--reason",
        "java_backend fail at 22:14",
        "--skip-wait",
        "-y",
        "--metrics-url",
        "http://127.0.0.1:1/nope",  # 让 baseline 跳过
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"

    # .env 应有 CANARY_ROOM_IDS= 空值
    new_content = env.read_text(encoding="utf-8")
    assert "\nCANARY_ROOM_IDS=\n" in new_content
    # 原值应该被注释保留
    assert "# CANARY_ROOM_IDS=r-test-1,r-test-2" in new_content
    # 其他字段未动
    assert "QWEN_API_KEY=sk-fake" in new_content
    assert "SOMETHING_ELSE=preserved" in new_content

    # audit log 写了
    audit = tmp_path / ".rollback-audit.log"
    assert audit.exists()
    audit_content = audit.read_text(encoding="utf-8")
    assert "java_backend fail at 22:14" in audit_content
    assert "before:" in audit_content
    assert "after:" in audit_content
    assert "env_backup:" in audit_content

    # 备份文件存在
    backups = list(tmp_path.glob(".env.rollback-*"))
    assert len(backups) == 1
    assert "r-test-1,r-test-2" in backups[0].read_text(encoding="utf-8")


def test_real_run_preserves_other_env_fields(tmp_path: Path) -> None:
    """回切只动 CANARY_ROOM_IDS，绝不动其他字段（生产 .env 含敏感密钥）。"""
    env = tmp_path / ".env"
    env.write_text(
        """QWEN_API_KEY=sk-very-secret
OTC_API_SECRET=do-not-touch
CANARY_ROOM_IDS=r1,r2
ENABLE_LANGFUSE=true
""",
        encoding="utf-8",
    )

    _run_rollback(
        tmp_path,
        "--reason",
        "preserve test",
        "--skip-wait",
        "-y",
        "--metrics-url",
        "http://127.0.0.1:1/nope",
    )
    after = env.read_text(encoding="utf-8")
    assert "QWEN_API_KEY=sk-very-secret" in after
    assert "OTC_API_SECRET=do-not-touch" in after
    assert "ENABLE_LANGFUSE=true" in after


def test_audit_log_appends_not_overwrites(tmp_path: Path) -> None:
    """多次回切 → audit log 追加，不能覆盖（事故复盘要全历史）。"""
    _make_env(tmp_path, "r1")
    _run_rollback(
        tmp_path, "--reason", "first", "--skip-wait", "-y",
        "--metrics-url", "http://127.0.0.1:1/nope",
    )
    audit = tmp_path / ".rollback-audit.log"
    first_size = audit.stat().st_size

    # 二次回切（先恢复 .env）
    env = tmp_path / ".env"
    content = env.read_text(encoding="utf-8")
    env.write_text(content.replace("CANARY_ROOM_IDS=\n", "CANARY_ROOM_IDS=r2\n"), encoding="utf-8")

    _run_rollback(
        tmp_path, "--reason", "second", "--skip-wait", "-y",
        "--metrics-url", "http://127.0.0.1:1/nope",
    )
    assert audit.stat().st_size > first_size
    text = audit.read_text(encoding="utf-8")
    assert "first" in text
    assert "second" in text


# ============================================================
# 安全：.env 备份权限 600
# ============================================================


@pytest.mark.skipif(
    os.name == "nt", reason="Windows 无 chmod 概念"
)
def test_backup_has_strict_permissions(tmp_path: Path) -> None:
    _make_env(tmp_path, "r1")
    _run_rollback(
        tmp_path, "--reason", "test", "--skip-wait", "-y",
        "--metrics-url", "http://127.0.0.1:1/nope",
    )
    backup = next(tmp_path.glob(".env.rollback-*"))
    mode = backup.stat().st_mode & 0o777
    # 至少 group/other 不可读（敏感密钥）
    assert mode & 0o077 == 0, f"backup perms {oct(mode)} 暴露给 group/other"
