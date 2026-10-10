-- LangGraph initialization in the database selected by the caller.
-- MySQL 8.0.19 <= version < 9.6.0; checkpoint adapter pinned to 3.0.0.
-- Fresh installation only. Existing Java tables and old databases are untouched.

CREATE TABLE IF NOT EXISTS `langgraph_checkpoint_migrations` (
  `v` int NOT NULL COMMENT '已应用的检查点结构迁移版本号，从 0 开始',
  PRIMARY KEY (`v`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='LangGraph 检查点表结构迁移版本记录';

CREATE TABLE IF NOT EXISTS `langgraph_checkpoints` (
  `thread_id` varchar(150) NOT NULL COMMENT '会话线程标识，对应 conversation_id',
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '' COMMENT '检查点命名空间，用于区分主图和嵌套子图；主图为空字符串',
  `checkpoint_id` varchar(150) NOT NULL COMMENT '检查点标识',
  `parent_checkpoint_id` varchar(150) DEFAULT NULL COMMENT '父检查点标识，用于关联历史状态',
  `type` varchar(150) DEFAULT NULL COMMENT '检查点序列化类型标记，保留的兼容字段',
  `checkpoint` json NOT NULL COMMENT '检查点状态及通道版本信息，JSON 格式',
  `metadata` json NOT NULL DEFAULT (_utf8mb4'{}') COMMENT '检查点元数据，包含来源、执行步数及父图信息',
  `checkpoint_ns_hash` binary(16) NOT NULL COMMENT '命名空间的 MD5 二进制摘要，用于联合主键',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`),
  KEY `checkpoints_thread_id_idx` (`thread_id`),
  KEY `checkpoints_checkpoint_id_idx` (`checkpoint_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='LangGraph 会话状态检查点';

CREATE TABLE IF NOT EXISTS `langgraph_checkpoint_blobs` (
  `thread_id` varchar(150) NOT NULL COMMENT '会话线程标识，对应 conversation_id',
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '' COMMENT '检查点命名空间，用于区分主图和嵌套子图',
  `channel` varchar(150) NOT NULL COMMENT '状态通道名称，对应图中的状态字段',
  `version` varchar(150) NOT NULL COMMENT '通道状态版本标识',
  `type` varchar(150) NOT NULL COMMENT '通道值序列化类型标记；empty 表示该版本无值',
  `blob` longblob COMMENT '序列化后的通道状态数据；无值时为空',
  `checkpoint_ns_hash` binary(16) NOT NULL COMMENT '命名空间的 MD5 二进制摘要，用于联合主键',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`channel`,`version`),
  KEY `checkpoint_blobs_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='LangGraph 检查点通道状态二进制数据';

CREATE TABLE IF NOT EXISTS `langgraph_checkpoint_writes` (
  `thread_id` varchar(150) NOT NULL COMMENT '会话线程标识，对应 conversation_id',
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '' COMMENT '检查点命名空间，用于区分主图和嵌套子图',
  `checkpoint_id` varchar(150) NOT NULL COMMENT '本次任务写入关联的检查点标识',
  `task_id` varchar(150) NOT NULL COMMENT '产生本次写入的节点任务标识',
  `idx` int NOT NULL COMMENT '任务内写入序号，特殊内部通道可使用负数',
  `channel` varchar(150) NOT NULL COMMENT '待写入的状态字段或内部通道名称',
  `type` varchar(150) DEFAULT NULL COMMENT '待写入值的序列化类型标记',
  `blob` longblob NOT NULL COMMENT '序列化后的待写入数据',
  `checkpoint_ns_hash` binary(16) NOT NULL COMMENT '命名空间的 MD5 二进制摘要，用于联合主键',
  `task_path` varchar(2000) NOT NULL DEFAULT '' COMMENT '节点任务在图中的执行路径',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`,`task_id`,`idx`),
  KEY `checkpoint_writes_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='LangGraph 节点任务的检查点待合并写入记录';

CREATE TABLE IF NOT EXISTS langgraph_message_log (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT COMMENT '消息流水自增主键',
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
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '记录创建时间，毫秒精度',
    UNIQUE KEY uk_message_id (message_id),
    KEY idx_conversation (conversation_id, created_at),
    KEY idx_room (room_id, created_at),
    KEY idx_user (user_id, created_at),
    KEY idx_product_intent (product_type, intent, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='消息处理流水';

CREATE TABLE IF NOT EXISTS langgraph_node_trace (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT COMMENT '节点追踪记录自增主键',
    message_id      VARCHAR(64)     NOT NULL COMMENT '关联的企微消息 ID',
    thread_id       VARCHAR(128)    NOT NULL COMMENT 'LangGraph thread_id',
    trace_id        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '单次 graph 调用关联 ID（ADR 0004，关联 LangFuse）',
    node_name       VARCHAR(64)     NOT NULL COMMENT '图中执行的节点名称',
    step_index      INT             NOT NULL COMMENT '节点执行顺序',
    input_preview   TEXT            COMMENT '输入预览',
    output_preview  TEXT            COMMENT '输出预览',
    status          VARCHAR(16)     NOT NULL COMMENT 'success/error',
    error           TEXT COMMENT '节点失败时的错误摘要',
    duration_ms     INT COMMENT '节点执行耗时，单位毫秒',
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '记录创建时间，毫秒精度',
    KEY idx_message (message_id, step_index),
    KEY idx_thread (thread_id, created_at),
    KEY idx_node_status (node_name, status, created_at),
    KEY idx_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='节点执行追踪';

CREATE TABLE IF NOT EXISTS langgraph_shadow_compare (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT COMMENT '双跑对比记录自增主键',
    message_id      VARCHAR(64)     NOT NULL COMMENT '关联的消息或评估用例标识',
    primary_path    VARCHAR(32)     NOT NULL COMMENT 'langgraph/dify',
    primary_result  JSON COMMENT '主执行链路返回的结果，JSON 格式',
    shadow_result   JSON COMMENT '影子链路返回的结果，JSON 格式',
    is_equal        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '两条链路结果是否一致：0 不一致，1 一致',
    diff_detail     JSON            COMMENT '不一致字段明细',
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '对比记录创建时间，毫秒精度',
    KEY idx_equal (is_equal, created_at),
    KEY idx_message (message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='Shadow 双跑对比';

CREATE TABLE IF NOT EXISTS langgraph_user_feedback (
    id              BIGINT          PRIMARY KEY AUTO_INCREMENT COMMENT '人工反馈记录自增主键',
    message_id      VARCHAR(64)     NOT NULL COMMENT '被反馈的企微消息 ID',
    feedback_type   VARCHAR(32)     NOT NULL COMMENT 'incorrect/partial/good',
    category        VARCHAR(64)     COMMENT '问题分类',
    comment         TEXT COMMENT '反馈人填写的补充说明',
    reporter_id     VARCHAR(64) COMMENT '反馈人标识',
    created_at      TIMESTAMP(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '反馈创建时间，毫秒精度',
    handled_at      TIMESTAMP(3) COMMENT '反馈处理时间，毫秒精度；空值表示未记录处理时间',
    handled_by      VARCHAR(64) COMMENT '反馈处理人标识',
    KEY idx_message (message_id),
    KEY idx_type (feedback_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='用户反馈';

CREATE TABLE IF NOT EXISTS langgraph_alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY COMMENT '当前已应用的 Alembic 迁移版本标识'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='LangGraph 应用数据库结构迁移版本记录';

INSERT IGNORE INTO langgraph_checkpoint_migrations (v) VALUES (0), (1), (2), (3), (4), (5), (6), (7), (8), (9), (10), (11), (12), (13), (14), (15), (16), (17), (18), (19), (20), (21);

INSERT IGNORE INTO langgraph_alembic_version (version_num) VALUES ('0001_request_replay');
