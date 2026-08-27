-- ============================================================
-- 业务数据表（在 otc_agent_business 库中创建）
-- ============================================================

USE otc_agent_business;

-- 1. 消息流水表：每一条从企微来的指令都落库
CREATE TABLE IF NOT EXISTS message_log (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    message_id      VARCHAR(64)     NOT NULL COMMENT '企微消息 ID',
    conversation_id VARCHAR(128)    NOT NULL COMMENT '企微会话 ID',
    room_id         VARCHAR(128)    NOT NULL COMMENT '企微群 ID',
    user_id         VARCHAR(64)     NOT NULL COMMENT '发送者 userId',
    guid            VARCHAR(64)     COMMENT '消息去重标识',
    raw_content     MEDIUMTEXT      NOT NULL COMMENT '原始消息',
    quote_content   MEDIUMTEXT      COMMENT '引用消息',
    attachments     JSON            COMMENT '附件列表（图片/Excel）',
    product_type    VARCHAR(32)     COMMENT '产品类型：option/swap/option_close',
    intent          VARCHAR(64)     COMMENT '识别意图',
    api_code        INT             COMMENT '后端返回 code',
    api_result      TEXT            COMMENT '后端返回内容',
    error           TEXT            COMMENT '错误信息',
    processed_by    VARCHAR(32)     COMMENT 'langgraph / dify 标记',
    latency_ms      INT             COMMENT '端到端耗时',
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_message_id (message_id),
    KEY idx_conversation (conversation_id, created_at),
    KEY idx_room (room_id, created_at),
    KEY idx_user (user_id, created_at),
    KEY idx_product_intent (product_type, intent, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息处理流水';

-- 2. 节点执行 trace 表：用于故障定位
CREATE TABLE IF NOT EXISTS node_trace (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    message_id      VARCHAR(64)     NOT NULL,
    thread_id       VARCHAR(128)    NOT NULL COMMENT 'LangGraph thread_id',
    trace_id        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '单次 graph 调用关联 ID（ADR 0004/#156，关联 LangFuse）',
    node_name       VARCHAR(64)     NOT NULL,
    step_index      INT             NOT NULL COMMENT '节点执行顺序',
    input_preview   TEXT            COMMENT '输入预览',
    output_preview  TEXT            COMMENT '输出预览',
    status          VARCHAR(16)     NOT NULL COMMENT 'success/error',
    error           TEXT,
    duration_ms     INT,
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_message (message_id, step_index),
    KEY idx_thread (thread_id, created_at),
    KEY idx_node_status (node_name, status, created_at),
    KEY idx_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='节点执行追踪';
-- 存量库迁移（2026-08-27 #156）：
--   ALTER TABLE node_trace ADD COLUMN trace_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '单次 graph 调用关联 ID' AFTER thread_id,
--                          ADD KEY idx_trace (trace_id);

-- 3. Shadow 对比结果表（灰度期使用）
CREATE TABLE IF NOT EXISTS shadow_compare (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    message_id      VARCHAR(64)     NOT NULL,
    primary_path    VARCHAR(32)     NOT NULL COMMENT 'langgraph/dify',
    primary_result  JSON,
    shadow_result   JSON,
    is_equal        TINYINT(1)      NOT NULL DEFAULT 0,
    diff_detail     JSON            COMMENT '不一致字段明细',
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    KEY idx_equal (is_equal, created_at),
    KEY idx_message (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Shadow 双跑对比';

-- 4. 人工反馈表（用户点击"反馈不准确"时记录）
CREATE TABLE IF NOT EXISTS user_feedback (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT,
    message_id      VARCHAR(64)     NOT NULL,
    feedback_type   VARCHAR(32)     NOT NULL COMMENT 'incorrect/partial/good',
    category        VARCHAR(64)     COMMENT '问题分类',
    comment         TEXT,
    reporter_id     VARCHAR(64),
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    handled_at      TIMESTAMP(3),
    handled_by      VARCHAR(64),
    KEY idx_message (message_id),
    KEY idx_type (feedback_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户反馈';
