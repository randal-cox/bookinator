from tools import qwen_semantic_fork_experiment as experiment


def test_rank_action_passages_prefers_multi_action_uncertain_sequence() -> None:
    source = (
        "The room stood empty.\n\n"
        "She looked at the window.\n\n"
        "The lady started back, then slipped down upon the floor and, as I thought, hid under the bed.\n\n"
        "They walked home."
    )
    selected = experiment.rank_action_passages(source, limit=1)
    assert len(selected) == 1
    assert "as I thought" in selected[0]["exact_source"]
    assert selected[0]["risk_score"] > selected[0]["selection_score"]


def test_action_audits_are_small_cached_batches() -> None:
    passages = [
        {"passage_id": f"P{index:04d}", "exact_source": "She moved.", "character_start": index, "character_end": index + 10}
        for index in range(1, 7)
    ]
    branches = experiment.branch_definitions(True, passages)
    action_branches = [item for item in branches if str(item["id"]).startswith("action-audit-")]
    assert [item["id"] for item in action_branches] == ["action-audit-1", "action-audit-2"]
    for branch in action_branches:
        schema = branch["properties"]["action_audit"]
        assert schema["minItems"] == 3
        assert schema["maxItems"] == 3


def test_deterministic_validation_triggers_only_concrete_repairs() -> None:
    source = "She started back, then slipped down upon the floor."
    passage = experiment.server.source_evidence_passages(source)[0]
    ref = {
        "passage_id": passage["id"], "quote": passage["text"],
        "character_start": passage["characterStart"], "character_end": passage["characterEnd"],
    }
    branches = [
        {
            "id": "identity", "status": "complete",
            "result": {"cast": [
                {"canonical_name": "First", "aliases": ["Madame"], "evidence_ref": ref},
                {"canonical_name": "Second", "aliases": ["Madame"], "evidence_ref": ref},
            ]},
        },
        {
            "id": "action-audit-1", "status": "complete",
            "result": {"action_audit": [{"passage_id": passage["id"], "actions": [], "evidence_ref": ref}]},
        },
        {
            "id": "assessment", "status": "complete",
            "result": {"assessment": {"dimensions": {"saleability": {"applicable": False, "evidence": []}}}},
        },
    ]
    selected = [{"passage_id": passage["id"], "exact_source": passage["text"]}]
    issues = experiment.deterministic_validation(branches, source, selected)
    kinds = {item["kind"] for item in issues}
    assert {"alias_collision", "empty_high_risk_action_audit", "saleability_marked_inapplicable"} <= kinds
