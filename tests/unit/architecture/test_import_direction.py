"""Imports must point inward: adapters -> application -> domain, never the other way.

The app is laid out as ports and adapters. The domain (entities, value objects, ports) knows
nothing about frameworks or databases; the application layer uses the domain; adapters (the
API, the database, the model provider) use both. That only stays true if nothing in an inner
layer imports an outer one, and a lazy import inside a function breaks it just as much as one
at the top of a file. This test reads every source file and checks.

`KNOWN_VIOLATIONS` is a ratchet, like the lint baseline: the list may only shrink. A new
wrong-direction import fails the test; so does an entry that no longer matches anything, so
the list cannot go stale.
"""

import ast
from pathlib import Path

import pytest

import agent_system

ROOT = Path(agent_system.__file__).parent

# layer -> the layers it must not import
FORBIDDEN = {
    "domain": ("application", "adapters", "composition_root", "evals"),
    "application": ("adapters", "composition_root", "evals"),
    "adapters.outbound": ("adapters.inbound", "evals"),
}

# (importing module, imported module): why it is still here.
KNOWN_VIOLATIONS = {
    # These three build a model client themselves. They are adapters in all but location and
    # should move to adapters/outbound/llm; tools.py imports them by their current path.
    ("application.services.contradiction_detector", "adapters.outbound.llm.provider"): "move to adapters/outbound/llm",
    ("application.services.expertise_profiler", "adapters.outbound.llm.provider"): "move to adapters/outbound/llm",
    ("application.services.datetime_parser", "adapters.outbound.llm.provider"): "move to adapters/outbound/llm",
    # The factory reads the secret key from settings; the class itself is pure.
    ("domain.utils.encryption", "composition_root.config"): "pass the secret key in from the composition root",
}


def _inside(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def find_violations(root: Path = ROOT) -> set[tuple[str, str]]:
    found = set()
    for path in root.rglob("*.py"):
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        banned = next((targets for layer, targets in FORBIDDEN.items() if _inside(module, layer)), None)
        if banned is None:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported = [node.module]
            elif isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            else:
                continue
            for name in imported:
                if not name.startswith("agent_system."):
                    continue
                target = name.removeprefix("agent_system.")
                if any(_inside(target, layer) for layer in banned):
                    found.add((module, target))
    return found


@pytest.mark.unit
def test_no_new_wrong_direction_imports():
    new = find_violations() - set(KNOWN_VIOLATIONS)
    assert not new, "inner layer imports an outer one (pass the dependency in instead): " + ", ".join(
        f"{src} -> {dst}" for src, dst in sorted(new))


@pytest.mark.unit
def test_known_violations_list_has_no_stale_entries():
    fixed = set(KNOWN_VIOLATIONS) - find_violations()
    assert not fixed, f"fixed, so remove from KNOWN_VIOLATIONS: {sorted(fixed)}"


@pytest.mark.unit
def test_the_check_sees_lazy_imports(tmp_path):
    bad = tmp_path / "domain" / "thing.py"
    bad.parent.mkdir()
    bad.write_text("def f():\n    from agent_system.adapters.outbound.persistence import Database\n    return Database\n")
    assert find_violations(tmp_path) == {("domain.thing", "adapters.outbound.persistence")}
