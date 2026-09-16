"""提示词加载器解析测试——嵌套围栏截断 bug 回归(P1 迁移期发现)。

bug:_MD_SYSTEM_RE 非贪婪匹配遇 [system] 段内嵌套的 ``` 围栏在第一个内层
围栏处提前截断。修复后:闭合围栏必须后跟下一节标题(## [...])或文件尾。
"""
from __future__ import annotations

from app.prompts import (
    _parse_prompt_md,  # type: ignore[attr-defined]
    clear_cache,
    load_prompt,
)

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
    def test_place_close_loads_fully(self):
        """P1 迁移期确认:长 system(大量内嵌围栏标记)不得被提前截断。"""
        clear_cache()
        p = load_prompt("option_close", "place_close")
        assert len(p.system) > 3000, f"place_close system 疑似截断: {len(p.system)}"
