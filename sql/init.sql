-- ============================================================
-- 场外衍生品 AI 指令助手 - MySQL 初始化脚本
-- ============================================================
-- 说明：
--   1. otc_agent_checkpoint 库：存放 LangGraph checkpoint 数据
--      （表结构由 AIOMySQLSaver.setup() 自动创建，无需手动建表）
--   2. otc_agent_business 库：业务审计、日志、trace
--
-- MySQL 版本要求：8.0.19 <= version < 9.6.0
--
-- Collation 选择说明：
--   统一使用 utf8mb4_0900_ai_ci（MySQL 8.0 默认），确保与 LangGraph
--   MySQL checkpointer 内部 JSON_TABLE 输出的 collation 一致，避免
--   "Illegal mix of collations" 错误。中文存储/比较不受影响。
-- ============================================================

-- 创建两个独立库（checkpoint 与业务数据物理隔离，便于后续单独扩容）
CREATE DATABASE IF NOT EXISTS otc_agent_checkpoint
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS otc_agent_business
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

-- 授权
GRANT ALL PRIVILEGES ON otc_agent_checkpoint.* TO 'otc_agent'@'%';
GRANT ALL PRIVILEGES ON otc_agent_business.* TO 'otc_agent'@'%';
FLUSH PRIVILEGES;
