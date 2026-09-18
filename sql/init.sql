-- LangGraph initialization in the database selected by the caller.
-- MySQL 8.0.19 <= version < 9.6.0; checkpoint adapter pinned to 3.0.0.
-- Fresh installation only. Existing Java tables and old databases are untouched.

CREATE TABLE IF NOT EXISTS `langgraph_checkpoint_migrations` (
  `v` int NOT NULL,
  PRIMARY KEY (`v`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `langgraph_checkpoints` (
  `thread_id` varchar(150) NOT NULL,
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '',
  `checkpoint_id` varchar(150) NOT NULL,
  `parent_checkpoint_id` varchar(150) DEFAULT NULL,
  `type` varchar(150) DEFAULT NULL,
  `checkpoint` json NOT NULL,
  `metadata` json NOT NULL DEFAULT (_utf8mb4'{}'),
  `checkpoint_ns_hash` binary(16) NOT NULL,
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`),
  KEY `checkpoints_thread_id_idx` (`thread_id`),
  KEY `checkpoints_checkpoint_id_idx` (`checkpoint_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `langgraph_checkpoint_blobs` (
  `thread_id` varchar(150) NOT NULL,
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '',
  `channel` varchar(150) NOT NULL,
  `version` varchar(150) NOT NULL,
  `type` varchar(150) NOT NULL,
  `blob` longblob,
  `checkpoint_ns_hash` binary(16) NOT NULL,
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`channel`,`version`),
  KEY `checkpoint_blobs_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `langgraph_checkpoint_writes` (
  `thread_id` varchar(150) NOT NULL,
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '',
  `checkpoint_id` varchar(150) NOT NULL,
  `task_id` varchar(150) NOT NULL,
  `idx` int NOT NULL,
  `channel` varchar(150) NOT NULL,
  `type` varchar(150) DEFAULT NULL,
  `blob` longblob NOT NULL,
  `checkpoint_ns_hash` binary(16) NOT NULL,
  `task_path` varchar(2000) NOT NULL DEFAULT '',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`,`task_id`,`idx`),
  KEY `checkpoint_writes_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS langgraph_message_log (
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
    reply_text      MEDIUMTEXT      COMMENT '回复文本（请求级幂等回放，ADR 0024 D4；NULL = 处理中）',
    response_json   JSON            COMMENT '完整 HTTP 响应快照',
    http_status     SMALLINT        NOT NULL DEFAULT 200 COMMENT '首次响应的 HTTP 状态',
    latency_ms      INT             COMMENT '端到端耗时',
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uk_message_id (message_id),
    KEY idx_conversation (conversation_id, created_at),
    KEY idx_room (room_id, created_at),
    KEY idx_user (user_id, created_at),
    KEY idx_product_intent (product_type, intent, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='消息处理流水';

CREATE TABLE IF NOT EXISTS langgraph_node_trace (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='节点执行追踪';

CREATE TABLE IF NOT EXISTS langgraph_shadow_compare (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Shadow 双跑对比';

CREATE TABLE IF NOT EXISTS langgraph_user_feedback (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户反馈';

CREATE TABLE IF NOT EXISTS langgraph_alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT IGNORE INTO langgraph_checkpoint_migrations (v) VALUES (0), (1), (2), (3), (4), (5), (6), (7), (8), (9), (10), (11), (12), (13), (14), (15), (16), (17), (18), (19), (20), (21);

INSERT IGNORE INTO langgraph_alembic_version (version_num) VALUES ('0001_request_replay');
