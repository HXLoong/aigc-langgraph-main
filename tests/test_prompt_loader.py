"""提示词加载器解析测试——嵌套围栏截断 bug 回归(P1 迁移期发现)。

bug:_MD_SYSTEM_RE 非贪婪匹配遇 [system] 段内嵌套的 ``` 围栏在第一个内层
围栏处提前截断。修复后:闭合围栏必须后跟下一节标题(## [...])或文件尾。
"""
from __future__ import annotations

from app.prompts import clear_cache, load_prompt
from app.prompts import _parse_prompt_md  # type: ignore[attr-defined]

_NESTED_MD = """# 测试提示词

## [system]

```
你是分类器。

输出格式示例:

```json
{"type": "a"}
```

以上示例后还有重要内容:必须完整加载到这一行。
```

## [user]

```
query: {{#x.y#}}
```
"""


class TestNestedFenceParsing:
    def test_system_not_truncated_at_inner_fence(self):
        system, user = _parse_prompt_md(_NESTED_MD)
        assert "必须完整加载到这一行" in system
        assert '{"type": "a"}' in system

    def test_user_section_intact(self):
        _, user = _parse_prompt_md(_NESTED_MD)
        assert "query" in user

    def test_plain_prompt_still_works(self):
        md = "## [system]\n\n```\n简单系统提示词\n```\n\n## [user]\n\n```\nhi\n```\n"
        system, user = _parse_prompt_md(md)
        assert system == "简单系统提示词"
        assert user == "hi"


class TestRealFileRegression:
    def test_cancel_close_loads_fully(self):
        """P1 迁移期确认:cancel_close.md(4717 字符,26 个围栏标记)曾被截断到 1049。"""
        clear_cache()
        p = load_prompt("option_close", "cancel_close")
        assert len(p.system) > 3000, f"cancel_close system 疑似截断: {len(p.system)}"
