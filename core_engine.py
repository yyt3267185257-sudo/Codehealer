from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, TypedDict

import docker
from docker.errors import APIError, DockerException, ImageNotFound
from docker.models.containers import Container
from langgraph.graph import END, StateGraph
from requests.exceptions import ReadTimeout


class AgentState(TypedDict):
    task_description: str
    target_code: str
    test_code: str
    sandbox_output: str
    is_resolved: bool
    iterations: int


class SandboxExecutionResult(TypedDict):
    exit_code: int
    output: str


class CodeFixer(Protocol):
    def fix(self, *, task_description: str, target_code: str, sandbox_output: str) -> str:
        """返回修复后的完整 Python 源码。"""


class DockerSandboxExecutor:
    """在隔离 Docker 容器中运行候选代码和 pytest 测试。"""

    def __init__(
        self,
        *,
        image: str = "python:3.10-slim",
        timeout_seconds: int = 45,
        install_pytest: bool = True,
        network_disabled: bool = False,
    ) -> None:
        self._image = image
        self._timeout_seconds = timeout_seconds
        self._install_pytest = install_pytest
        self._network_disabled = network_disabled
        try:
            self._client = docker.from_env()
        except DockerException as exc:
            raise RuntimeError(
                "Docker 不可用。请确认 Docker Desktop 或 Docker daemon 已启动。"
            ) from exc

    def run_pytest(self, *, target_code: str, test_code: str) -> SandboxExecutionResult:
        """对目标代码执行 pytest，并返回合并日志和退出码。"""

        container: Optional[Container] = None
        with tempfile.TemporaryDirectory(prefix="codehealer-sandbox-") as temp_dir:
            workdir = Path(temp_dir)
            (workdir / "solution.py").write_text(target_code, encoding="utf-8")
            (workdir / "test_code.py").write_text(test_code, encoding="utf-8")

            command = self._build_command()
            volumes: Mapping[str, Mapping[str, str]] = {
                str(workdir.resolve()): {"bind": "/workspace", "mode": "rw"}
            }

            try:
                self._ensure_image()
                container = self._client.containers.run(
                    self._image,
                    command=command,
                    detach=True,
                    working_dir="/workspace",
                    volumes=volumes,
                    network_disabled=self._network_disabled,
                    mem_limit="256m",
                    pids_limit=128,
                    read_only=False,
                    stdout=True,
                    stderr=True,
                )

                wait_result = container.wait(timeout=self._timeout_seconds)
                exit_code = int(wait_result.get("StatusCode", 1))
                output = self._read_logs(container)
                return {"exit_code": exit_code, "output": output}

            except (TimeoutError, ReadTimeout):
                timeout_message = f"沙箱执行超过 {self._timeout_seconds} 秒，已超时。"
                if container is not None:
                    self._kill_container(container)
                    output = self._read_logs(container)
                    timeout_message = f"{timeout_message}\n{output}".strip()
                return {"exit_code": 124, "output": timeout_message}

            except ImageNotFound as exc:
                return {
                    "exit_code": 125,
                    "output": f"Docker 镜像不存在且拉取失败：{exc}",
                }

            except (APIError, DockerException, OSError) as exc:
                return {
                    "exit_code": 125,
                    "output": f"Docker 沙箱执行失败：{type(exc).__name__}: {exc}",
                }

            finally:
                if container is not None:
                    self._remove_container(container)

    def _build_command(self) -> list[str]:
        install = ""
        if self._install_pytest:
            install = "python -m pip install --disable-pip-version-check -q pytest && "
        return [
            "sh",
            "-lc",
            f"{install}python -m pytest -q /workspace/test_code.py",
        ]

    def _ensure_image(self) -> None:
        try:
            self._client.images.get(self._image)
        except ImageNotFound:
            self._client.images.pull(self._image)

    @staticmethod
    def _read_logs(container: Container) -> str:
        try:
            raw_logs = container.logs(stdout=True, stderr=True)
            return raw_logs.decode("utf-8", errors="replace")
        except DockerException as exc:
            return f"读取容器日志失败：{exc}"

    @staticmethod
    def _kill_container(container: Container) -> None:
        try:
            container.kill()
        except DockerException:
            pass

    @staticmethod
    def _remove_container(container: Container) -> None:
        try:
            container.remove(force=True)
        except DockerException:
            pass


class LangChainCoder:
    """由大模型驱动的代码修复组件，严格约束输出为纯代码。"""

    SYSTEM_PROMPT = """You are CodeHealer's repair engine.
You receive a Python source file and pytest failure output.
Return only the complete fixed Python source code.
Do not include Markdown fences, explanations, comments outside the code, or prose."""

    def __init__(self, *, llm: Optional[Any] = None, model_name: Optional[str] = None) -> None:
        if llm is None and model_name is None:
            raise ValueError("请提供 LangChain 聊天模型实例或 model_name。")
        self._llm = llm if llm is not None else self._init_model(model_name)

    def fix(self, *, task_description: str, target_code: str, sandbox_output: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        prompt = f"""Task:
{task_description}

Current Python code:
{target_code}

Sandbox pytest output:
{sandbox_output}

Return the complete fixed Python code only."""
        response = self._llm.invoke(
            [SystemMessage(content=self.SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        content = getattr(response, "content", response)
        if not isinstance(content, str):
            raise TypeError(f"LLM 返回了不支持的响应内容类型：{type(content)!r}")

        fixed_code = self._strip_markdown_fences(content).strip()
        if not fixed_code:
            raise ValueError("LLM 返回了空代码。")
        return fixed_code

    @staticmethod
    def _init_model(model_name: Optional[str]) -> Any:
        from langchain.chat_models import init_chat_model

        return init_chat_model(model_name)

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        stripped = content.strip()
        if not stripped.startswith("```"):
            return stripped

        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)


class CodeHealerEngine:
    """使用 LangGraph 编排代码生成和沙箱验证闭环。"""

    def __init__(self, *, sandbox: DockerSandboxExecutor, coder: CodeFixer) -> None:
        self._sandbox = sandbox
        self._coder = coder
        self.graph = self._build_graph()

    def run(self, initial_state: AgentState) -> AgentState:
        final_state = self.graph.invoke(initial_state)
        return AgentState(**final_state)

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("node_verifier", self._node_verifier)
        graph.add_node("node_coder", self._node_coder)
        graph.set_entry_point("node_verifier")
        graph.add_conditional_edges(
            "node_verifier",
            self._route_after_verifier,
            {
                "resolved": END,
                "retry": "node_coder",
                "exhausted": END,
            },
        )
        graph.add_edge("node_coder", "node_verifier")
        return graph.compile()

    def _node_verifier(self, state: AgentState) -> dict[str, object]:
        result = self._sandbox.run_pytest(
            target_code=state["target_code"],
            test_code=state["test_code"],
        )
        return {
            "sandbox_output": result["output"],
            "is_resolved": result["exit_code"] == 0,
        }

    def _node_coder(self, state: AgentState) -> dict[str, object]:
        fixed_code = self._coder.fix(
            task_description=state["task_description"],
            target_code=state["target_code"],
            sandbox_output=state["sandbox_output"],
        )
        return {
            "target_code": fixed_code,
            "iterations": state["iterations"] + 1,
        }

    @staticmethod
    def _route_after_verifier(state: AgentState) -> str:
        if state["is_resolved"]:
            return "resolved"
        if state["iterations"] >= 3:
            return "exhausted"
        return "retry"
