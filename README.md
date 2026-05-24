# CodeHealer

CodeHealer 是一个事件驱动型 Coding Agent 原型，用于从 GitHub Issue 出发，自动定位代码、生成修复、在 Docker 沙箱中运行 pytest 验证，并在通过后自动创建 Pull Request。

当前版本已经包含四个核心能力：

- Phase 1：LangGraph 状态机 + Docker 沙箱测试闭环
- Phase 2：接入真实 LLM，替换 MockCoder
- Phase 3：读取 GitHub Issue、更新仓库文件并创建 PR
- Phase 4：基于 ChromaDB 的代码级 RAG，自动检索疑似 Bug 文件

## 项目结构

```text
.
├── codehealer_phase1.py      # 核心引擎：AgentState、DockerSandboxExecutor、LangChainCoder、CodeHealerEngine
├── run_github_agent.py       # GitHub + RAG + LLM + Docker 沙箱 + PR 主流程
├── requirements.txt          # Python 依赖
└── README.md
```

## 环境要求

- Python 3.10+
- Docker Desktop 或可用的 Docker daemon
- GitHub Personal Access Token
- 兼容 OpenAI API 格式的 Chat/Embedding 服务

本项目当前默认适配阿里云通义千问兼容接口：

- Chat model：由 `LLM_MODEL_NAME` 指定
- Embedding model：代码中固定使用 `text-embedding-v1`

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置环境变量

在项目根目录创建 `.env`：

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

GITHUB_TOKEN=your_github_personal_access_token
TARGET_REPO=your_github_username/test-repo
TARGET_ISSUE_NUMBER=1
```

说明：

- `OPENAI_API_KEY`：LLM 和 Embedding 服务密钥
- `OPENAI_API_BASE`：OpenAI 兼容接口地址
- `LLM_MODEL_NAME`：用于代码修复的聊天模型
- `GITHUB_TOKEN`：需要具备读取仓库、创建分支、提交代码、创建 PR 的权限
- `TARGET_REPO`：目标仓库，格式为 `owner/repo`
- `TARGET_ISSUE_NUMBER`：要处理的 GitHub Issue 编号

## 本地沙箱 Demo

只运行 Phase 1/2 的本地修复闭环：

```bash
python codehealer_phase1.py
```

该脚本会构造一个包含除零错误的示例函数，先在 Docker 容器中运行 pytest，失败后调用 LLM 修复，再次验证。

## GitHub Agent Demo

运行完整 GitHub + RAG + Docker + PR 流程：

```bash
python run_github_agent.py
```

主流程如下：

1. 加载 `.env`
2. 读取 `TARGET_REPO` 和 `TARGET_ISSUE_NUMBER`
3. 拉取 Issue 标题和正文
4. 遍历默认分支下的 Python 文件
5. 使用 ChromaDB 构建内存向量库
6. 根据 Issue 描述检索 Top-1 疑似 Bug 文件
7. 将目标文件代码放入 `AgentState`
8. 使用 LangGraph 执行修复循环
9. Docker 沙箱中运行 pytest
10. 测试通过后创建修复分支并发起 PR

成功定位文件时会输出：

```text
💡 [RAG] 自动检索定位到疑似 Bug 文件: path/to/file.py
```

## 当前测试代码

`run_github_agent.py` 中的 `DEMO_TEST_CODE` 仍是演示用测试：

```python
from solution import safe_divide


def test_normal_division() -> None:
    assert safe_divide(10, 2) == 5


def test_division_by_zero_returns_zero() -> None:
    assert safe_divide(10, 0) == 0.0
```

这意味着当前最适合测试的问题是：目标仓库中存在一个 `safe_divide` 函数，并且除零行为需要修复。后续可以把这里替换成从仓库测试文件、Issue 附件或 Agent 生成的测试。

## 常见问题

### Docker is not available

请确认 Docker Desktop 已启动，并且当前终端可以执行：

```bash
docker ps
```

### Embedding 报 model does not exist

当前代码使用阿里云支持的：

```text
text-embedding-v1
```

如果你切换到 OpenAI 官方或其他服务商，需要同步修改 `CustomAliyunEmbeddings` 中的模型名。

### GitHub 创建 PR 失败

请检查：

- `GITHUB_TOKEN` 是否有目标仓库权限
- token 是否允许 contents write 和 pull requests write
- 目标仓库是否存在默认分支
- 是否已有同名分支或未关闭的重复 PR

### RAG 定位文件不准

当前 RAG 是最小闭环实现，只取 Top-1 代码块所属文件。后续可以升级为：

- Top-K 文件投票
- BM25 + Vector Hybrid Search
- 使用 AST/符号索引
- 检索测试文件和调用链
- 将候选文件片段一起喂给 LLM 做二次 rerank

## 安全提示

CodeHealer 会自动创建分支、提交代码并创建 Pull Request。请只在测试仓库或你明确授权的仓库中运行，不要把高权限 token 暴露到公开环境。

