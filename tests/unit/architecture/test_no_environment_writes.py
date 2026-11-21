"""The app never writes to the process environment.

The chat routes used to put the current user's model API key in `os.environ["OPENAI_API_KEY"]`
so that code further down could find it. The environment is shared by every request in the
process, so with two people chatting at once, one person's calls could run on the other's key.
The key is now passed as an argument. This test keeps it that way.
"""

import ast
from pathlib import Path

import pytest

import agent_system

ROOT = Path(agent_system.__file__).parent
WRITING_CALLS = {"putenv", "unsetenv"}                           # os.putenv(...)
WRITING_METHODS = {"update", "setdefault", "pop", "clear", "popitem"}  # os.environ.update(...)


def _is_environ(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "environ" or isinstance(node, ast.Name) and node.id == "environ"


def find_environment_writes(root: Path = ROOT) -> list[str]:
    found: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = list(node.targets)
            wrote = any(isinstance(t, ast.Subscript) and _is_environ(t.value) for t in targets)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                wrote = wrote or (node.func.attr in WRITING_METHODS and _is_environ(node.func.value))
                wrote = wrote or (node.func.attr in WRITING_CALLS and isinstance(node.func.value, ast.Name)
                                  and node.func.value.id == "os")
            if wrote:
                found.append((str(path.relative_to(root)), node.lineno))
    return [f"{name}:{line}" for name, line in sorted(found)]


@pytest.mark.unit
def test_nothing_writes_to_the_process_environment():
    assert find_environment_writes() == [], "pass the value as an argument instead of setting an environment variable"


@pytest.mark.unit
def test_the_check_sees_each_way_of_writing(tmp_path):
    (tmp_path / "bad.py").write_text(
        'import os\n'
        'os.environ["OPENAI_API_KEY"] = "k"\n'
        'os.environ.update(A="b")\n'
        'os.environ.setdefault("A", "b")\n'
        'os.putenv("A", "b")\n'
        'del os.environ["A"]\n'
        'x = os.environ.get("A")\n'           # reading is fine
    )
    assert find_environment_writes(tmp_path) == ["bad.py:2", "bad.py:3", "bad.py:4", "bad.py:5", "bad.py:6"]
