# CodeHealer

CodeHealer 是一个面向 Python 仓库的全自动智能代码修复 Agent。它可以读取 GitHub Issue，自动检索最相关的源码文件，调用大模型生成修复代码，在隔离 Docker 沙箱中执行 pytest 验证，并在验证通过后自动创建 Pull Request。

这个项目面向真实的软件维护场景，目标是把 Issue 解析、代码检索、补丁生成、沙箱验证和 GitHub 交付串成一个可审计、可扩展、可落地的闭环。

## 核心能力

- LangGraph 状态机编排
  - 使用显式状态图组织修复流程。
  - 先验证当前代码，再根据失败日志触发代码修复。
  - 支持失败重试、成功终止和最大迭代次数保护。

- 基于 ChromaDB 的代码级 RAG 检索
  - 遍历目标仓库默认分支下的 Python 源码文件。
  - 使用代码感知的分块策略切分源码。
  - 将代码块写入进程内 Chroma 向量库。
  - 根据 GitHub Issue 描述检索最相关的疑似 Bug 文件。

- Docker 沙箱安全验证隔离
  - 使用一次性 `python:3.10-slim` 容器执行候选代码和 pytest。
  - 捕获 stdout、stderr、退出码和超时错误。
  - 每次验证结束后清理容器，避免污染宿主环境。

- GitHub Issue 解析与 PR 自动交付
  - 读取指定 Issue 的标题和正文。
  - 创建独立修复分支。
  - 更新被检索定位的源码文件。
  - 在测试通过后自动创建 Pull Request。

## 目录结构

```text
.
|-- core_engine.py          # LangGraph 修复引擎、LLM 修复器、Docker 沙箱执行器
|-- run_github_agent.py     # GitHub 连接器、代码检索器和主运行入口
|-- requirements.txt        # Python 依赖
`-- README.md               # 项目说明文档
```

## 环境要求

- Python 3.10 或更高版本
- Docker Desktop 或可访问的 Docker daemon
- GitHub Personal Access Token
- 兼容 OpenAI API 协议的聊天模型接口
- 兼容 OpenAI API 协议的 Embedding 接口

当前代码中的 Embedding 适配器默认使用阿里云通义千问兼容接口模型：

```text
text-embedding-v1
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 环境配置

在项目根目录创建 `.env` 文件：

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

GITHUB_TOKEN=your_github_personal_access_token
TARGET_REPO=your_github_username/test-repo
TARGET_ISSUE_NUMBER=1
```

配置项说明：

- `OPENAI_API_KEY`：聊天模型和 Embedding 服务使用的 API Key。
- `OPENAI_API_BASE`：兼容 OpenAI 协议的 API Base URL。
- `LLM_MODEL_NAME`：用于生成代码修复的聊天模型名称。
- `GITHUB_TOKEN`：GitHub Token，需要具备读取仓库、创建分支、更新文件和创建 Pull Request 的权限。
- `TARGET_REPO`：目标仓库，格式为 `owner/repo`。
- `TARGET_ISSUE_NUMBER`：需要处理的 GitHub Issue 编号。

## 使用方法

确认 Docker 已启动后，在项目根目录运行：

```bash
python run_github_agent.py
```

运行后，CodeHealer 会执行以下流程：

1. 从 `.env` 加载运行配置。
2. 读取指定 GitHub Issue。
3. 遍历目标仓库默认分支下的 Python 源码文件。
4. 构建代码向量库并检索疑似 Bug 文件。
5. 将 Issue 描述、目标代码和测试代码写入 `AgentState`。
6. 使用 LangGraph 执行修复与验证循环。
7. 在 Docker 容器中运行 pytest。
8. 若验证通过，则创建修复分支并发起 Pull Request。

执行报告会输出检索定位文件、修复状态、迭代次数、沙箱日志和 Pull Request 地址。

## 当前验证用例

`run_github_agent.py` 当前内置了一段演示用 pytest：

```python
from solution import safe_divide


def test_normal_division() -> None:
    assert safe_divide(10, 2) == 5


def test_division_by_zero_returns_zero() -> None:
    assert safe_divide(10, 0) == 0.0
```

这段测试用于验证完整闭环是否可用。接入真实项目时，可以将 `DEMO_TEST_CODE` 替换为仓库内已有测试、由 Issue 生成的测试，或项目自定义验证命令。

## 架构概览

```text
GitHub Issue
    |
    v
GitHubConnector
    |
    v
CodebaseRetriever
    |
    v
ChromaDB 代码检索
    |
    v
CodeHealerEngine
    |
    +--> DockerSandboxExecutor
    |
    +--> LangChainCoder
    |
    v
验证通过的修复代码
    |
    v
GitHub Pull Request
```

## 实现说明

- 代码检索器会忽略 `test`、`tests`、`__pycache__`、`.venv` 和 `venv` 目录。
- 代码检索器会跳过 `test_*.py` 和 `*_test.py` 测试文件。
- Docker 沙箱会把候选代码写入 `solution.py`，把测试代码写入 `test_code.py`。
- 修复引擎会在测试失败后调用大模型生成新代码，并在达到最大迭代次数后停止。
- Pull Request 创建前会先创建独立分支；如果分支名冲突，会自动追加时间戳和递增后缀。

## 常见问题

### Docker 不可用

请确认 Docker Desktop 已启动，并在终端中验证：

```bash
docker ps
```

### Embedding 模型不存在

当前自定义 Embedding 适配器使用：

```text
text-embedding-v1
```

如果切换到其他服务商，请修改 `run_github_agent.py` 中的 `CustomAliyunEmbeddings` 默认模型名称。

### Pull Request 创建失败

请检查：

- `GITHUB_TOKEN` 是否有目标仓库权限。
- Token 是否允许创建分支、更新文件和创建 Pull Request。
- 目标仓库是否存在有效默认分支。
- 分支保护规则是否阻止自动提交。

### RAG 定位文件不准确

当前实现使用 Top-1 向量检索。对于更大的仓库，可以继续增强为：

- Top-K 文件投票
- 关键词检索和向量检索混合召回
- AST 或符号索引
- 测试文件和调用链检索
- 使用大模型对候选文件进行二次排序

## 安全提示

CodeHealer 可以创建分支、提交代码并创建 Pull Request。请只在你拥有或明确获授权的仓库中运行。请将 API Key 和 GitHub Token 放在 `.env` 中，并确保不会把密钥提交到代码仓库。

