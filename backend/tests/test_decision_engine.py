from services.decision_engine import DecisionContext, decision_engine


def test_synthesized_player_recommendation_contains_quant_metadata():
    enriched = decision_engine.synthesize_player_recommendation(
        {
            "web_name": "Saka",
            "predicted_xpts_next": 7.4,
            "predicted_start_prob": 0.91,
            "selected_by_percent": 32.5,
            "fdr_next": 2,
            "is_home_next": True,
            "form": 6.8,
            "form_trend": "rising",
        },
        context=DecisionContext(recommendation_type="captain", risk_preference="balanced"),
        baseline_score=7.0,
    )
    assert enriched["decision_score"] > 0
    assert 0 <= enriched["confidence_score"] <= 100
    assert enriched["floor_projection"] <= enriched["median_projection"] <= enriched["ceiling_projection"]
    assert enriched["validation_complete"] is True
    assert "explanation_summary" in enriched


def test_transfer_synthesis_marks_differentials_and_validation():
    synthesized = decision_engine.synthesize_transfer_suggestions(
        [
            {
                "player_out": {"web_name": "Mitoma", "predicted_xpts_next": 3.1},
                "player_in": {
                    "web_name": "Gordon",
                    "predicted_xpts_next": 6.1,
                    "predicted_start_prob": 0.86,
                    "selected_by_percent": 9.2,
                    "fdr_next": 2,
                    "is_home_next": True,
                    "form": 5.2,
                },
                "xpts_gain_next": 3.0,
                "xpts_gain_3gw": 7.8,
                "net_gain_3gw": 7.8,
                "recommendation": "MAKE",
                "reasoning": "Strong medium-term gain",
            }
        ],
        context=DecisionContext(recommendation_type="transfer", risk_preference="aggressive"),
    )
    rec = synthesized[0]
    assert rec["validation_complete"] is True
    assert rec["confidence_label"] in {"high", "medium", "low"}
    assert isinstance(rec["explanation_reasons"], list)


def test_shadow_payload_detects_changed_top_recommendation():
    payload = decision_engine.build_shadow_payload(
        current=[{"web_name": "Haaland"}],
        synthesized=[{"web_name": "Saka"}],
        label="captain",
    )
    assert payload["mode"] == "shadow"
    assert payload["changed_top_recommendation"] is True
