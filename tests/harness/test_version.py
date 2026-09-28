"""非 Git 的部署包也必须能通过实际代码指纹复现评测。"""
import subprocess


def test_deployed_package_reports_hash_when_git_metadata_is_unavailable(monkeypatch):
    """Git 只是辅助身份；缺 Git 时不丢失确定的代码内容版本。"""
    from harness import version

    def unavailable(*args, **kwargs):
        """模拟已打包环境，避免依赖开发机仓库信息。"""
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "check_output", unavailable)
    metadata = version.execution_metadata()
    assert metadata["commit"] == "unversioned"
    assert len(metadata["code_hash"]) == 64
