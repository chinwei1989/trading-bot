from __future__ import annotations

from tradingbot.ops.office3d import build_office_data


def test_two_floor_office_has_workflow_and_agent_spaces() -> None:
    data = build_office_data()
    assert len(data["floors"]) == 2
    workflow, agents = data["floors"]
    assert workflow["id"] == "workflow"
    assert agents["id"] == "agents"
    for required in ("Risk Vault", "Execution Gateway", "Quant Meeting", "Pantry"):
        assert any(required.lower() in room.lower() for room in workflow["rooms"])
    for required in ("Meeting Room", "WC", "Director Room", "Pantry", "Entertainment"):
        assert required in agents["rooms"]
    assert len(data["agents"]) == 12
    assert all(agent["floor"] == 1 for agent in data["agents"])


def test_each_squad_has_a_manager_and_a_floor_race() -> None:
    data = build_office_data()
    agents = {agent["id"]: agent for agent in data["agents"]}
    for squad in data["squads"]:
        assert squad["manager"] in agents
        assert agents[squad["manager"]]["role"]
    assert data["competition"]["teams"][0]["floor"] == 0
    assert data["competition"]["teams"][1]["floor"] == 1
