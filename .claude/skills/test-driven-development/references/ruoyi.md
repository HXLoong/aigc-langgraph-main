# ruoyi-vue-pro TDD Adaptations

## Choose the right test base class

| Scenario | Base class | Spring context |
|----------|-----------|----------------|
| Pure component, no Spring deps (e.g. `MailMessageParser`) | None — just `new` | No — fastest |
| Service with DB operations | `extends BaseDbUnitTest` | Yes — H2 in-memory |
| Controller layer | `extends BaseWebClientTest` | Yes — MockMvc |

`MailMessageParser` has zero Spring/DB dependencies. Always `new MailMessageParser()` directly.

## Use ruoyi test utilities — never reinvent them

```java
// Generate a fully-populated VO with random data
JobSaveReqVO req = randomPojo(JobSaveReqVO.class);

// Override specific fields after random fill
JobSaveReqVO req = randomPojo(JobSaveReqVO.class, o -> o.setCronExpression("0 0/1 * * * ? *"));

// Assert a ServiceException with a specific error code
assertServiceException(() -> jobService.createJob(req), JOB_CRON_EXPRESSION_VALID);

// Compare two POJOs ignoring specified fields
assertPojoEquals(expected, actual, "id", "createTime");
```

## Mock strategy

| Dependency type | How to handle |
|----------------|---------------|
| In-project Service (same module) | Use real impl — injected by `BaseDbUnitTest` |
| External system (Quartz, RabbitMQ, SMTP) | `@MockBean` — never trigger real calls in unit tests |
| Cross-module API (`AdminUserApi` etc.) | `@MockBean` — covered by integration tests |
| Static framework util (`SpringUtil`) | `mockStatic()` scoped to the test method |

## Spring Security context

Any Service that calls `SecurityFrameworkUtils.getLoginUserId()` will throw NPE without a mocked login user. Set it up in `@BeforeEach`:

```java
@BeforeEach
void mockLoginUser() {
    mockStatic(SecurityFrameworkUtils.class);
    when(SecurityFrameworkUtils.getLoginUserId()).thenReturn(1L);
}
```
