---
name: test-driven-development
description: 'TDD workflow: enforces Red-Green-Refactor cycle, test-first rules, and verification steps. Only trigger when the user explicitly invokes /test-driven-development or says "使用tdd" / "用tdd". Do NOT auto-trigger on general coding requests like "implement", "add", "fix", or "write".'
metadata:
  source: .claude/skills/test-driven-development/SKILL.md
---

> 自动生成自 `.claude/skills/test-driven-development/SKILL.md`（python scripts/sync_agents_md.py），禁止手改。

# Test-Driven Development (TDD)

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Delete means delete

## When to Use

**Always:** New features, bug fixes, refactoring, behavior changes

**Exceptions (ask your human partner):** Throwaway prototypes, generated code, configuration files

## Red-Green-Refactor

### RED — Write Failing Test

Write one minimal test showing what should happen.

```java
@Test
void retriesFailedOperations3Times() {
    AtomicInteger attempts = new AtomicInteger(0);

    String result = RetryUtil.retryOperation(() -> {
        if (attempts.incrementAndGet() < 3) throw new RuntimeException("fail");
        return "success";
    });

    assertThat(result).isEqualTo("success");
    assertThat(attempts.get()).isEqualTo(3);
}
```

Requirements: one behavior, clear name, real code (no mocks unless unavoidable).

### Verify RED — Watch It Fail

**MANDATORY. Never skip.**

```bash
mvn test -Dtest=RetryUtilTest
```

- Test must fail (not error)
- Failure message must match the missing feature
- Test passes immediately? You're testing existing behavior — fix the test.

### GREEN — Minimal Code

Write simplest code to pass the test. Don't add features, refactor other code, or "improve" beyond the test.

### Verify GREEN — Watch It Pass

**MANDATORY.**

```bash
mvn test -Dtest=RetryUtilTest
```

- New test passes
- All other tests still pass
- Test fails? Fix code, not test.

### REFACTOR — Clean Up

After green only: remove duplication, improve names, extract helpers. Keep tests green. Don't add behavior.

## Good Tests

| Quality | Good | Bad |
|---------|------|-----|
| **Minimal** | One thing. "and" in name? Split it. | `void validatesEmailAndDomainAndWhitespace()` |
| **Clear** | Name describes behavior | `void test1()` |
| **Shows intent** | Demonstrates desired API | Obscures what code should do |

## When Stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write wished-for API. Write assertion first. Ask your human partner. |
| Test too complicated | Design too complicated. Simplify interface. |
| Must mock everything | Code too coupled. Use dependency injection. |
| Test setup huge | Extract helpers. Still complex? Simplify design. |

## Debugging Integration

Bug found? Write failing test reproducing it. Follow TDD cycle. Test proves fix and prevents regression.

Never fix bugs without a test.

## Testing Anti-Patterns

When adding mocks or test utilities, read [testing-anti-patterns.md](testing-anti-patterns.md) to avoid common pitfalls:
- Testing mock behavior instead of real behavior
- Adding test-only methods to production classes
- Mocking without understanding dependencies

## Project-Specific Adaptations

- **ruoyi-vue-pro (this project)**: See [references/ruoyi.md](references/ruoyi.md) for test base classes, ruoyi utilities, mock strategy, and Security context setup.

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

No exceptions without your human partner's permission.
