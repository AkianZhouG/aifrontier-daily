import sys
from pathlib import Path
from types import SimpleNamespace

import frontier_daily.llm as llm
from frontier_daily.llm import PiRunner


def test_pi_runner_uses_configured_tool_model_and_disables_discovery(
    app_config, tmp_path, monkeypatch
):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        prompt_arg = next(value for value in command if value.startswith("@"))
        captured["prompt"] = Path(prompt_arg[1:]).read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    runner = PiRunner(
        app_config,
        tmp_path / "run",
        agent_settings={
            "agent_binary": sys.executable,
            "agent_provider": "local-provider",
            "agent_model": "local-model",
            "agent_thinking": "medium",
        },
    )

    result = runner._run("关注主题：本地代理工具", "edition")

    assert result == {"ok": True}
    command = captured["command"]
    assert command[0] == str(Path(sys.executable).resolve())
    assert command[command.index("--provider") + 1] == "local-provider"
    assert command[command.index("--model") + 1] == "local-model"
    assert command[command.index("--thinking") + 1] == "medium"
    assert "--no-tools" in command
    assert "--no-extensions" in command
    assert "--no-skills" in command
    assert "--skill" not in command
    assert "关注主题：本地代理工具" in captured["prompt"]
