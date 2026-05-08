# Dify 工作流同步工具

从内网 Dify 平台下载工作流 YAML 到本地 `yaml/` 目录，可选自动推送到 Git 分支。

## 文件结构

```
dify/
├── sync.py          # 同步脚本
├── yaml/            # 下载的 YAML 文件
│   ├── 主干工作流.yml
│   ├── 标的智能化推断和分词工具.yml
│   ├── 标的相关性排序工具.yml
│   ├── 场外交易-期权工具.yml
│   └── 场外交易-互换工具.yml
└── README.md
```

## 用法

### 基本用法

```bash
# 仅下载 YAML 到本地
python dify/sync.py --email <邮箱> --password <密码>

# 下载并自动推送
python dify/sync.py --email <邮箱> --password <密码> --push

# 推送到指定分支（默认 feature-yaml）
python dify/sync.py --email <邮箱> --password <密码> --push --target-branch feature-hyk
```

### 通过环境变量配置

```bash
export DIFY_EMAIL="your-email@example.com"
export DIFY_PASSWORD="your-password"
python dify/sync.py          # 自动读取环境变量
python dify/sync.py --push   # 下载 + 推送
```

## 工作流列表

脚本会同步以下 5 个工作流：

| 工作流 ID | 名称 | 用途 |
|-----------|------|------|
| `d6c0ea8b-...` | 主干工作流 | 主路由与编排 |
| `07c56e04-...` | 标的智能化推断和分词工具 | Ticker Agent |
| `d6a4f5e1-...` | 标的相关性排序工具 | 标的排序 |
| `1f6dcea0-...` | 场外交易-期权工具 | 期权业务 |
| `d8f57e9c-...` | 场外交易-互换工具 | 互换业务 |

## 工作流程

1. 登录 Dify 内网平台 (`http://agent.smart-zone-dev.gf.com.cn`)
2. 遍历工作流列表，调用导出 API 下载 YAML
3. 保存到 `dify/yaml/` 目录（按工作流名称命名）
4. 若指定 `--push`，自动 commit 变更并推送到目标分支

## 依赖

- Python 3.11+（仅标准库，无第三方依赖）
- 需要访问内网 Dify 平台（VPN）

## 与代码库的关系

下载的工作流 YAML 是 **只读资产**，与 `app/prompts/` 目录对应：
- YAML 中的 LLM 节点提示词通过 `scripts/export_dify_prompts.py` 导出为 `.md` 文件
- 提示词加载与使用规范见 `.claude/rules/prompt-management.md`
