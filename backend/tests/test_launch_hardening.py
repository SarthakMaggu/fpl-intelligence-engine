import pandas as pd

from models.ml.minutes_model import MinutesModel
from services.cache_service import make_cache_key


def test_minutes_state_probabilities_sum_to_one():
    model = MinutesModel()
    df = pd.DataFrame(
        [
            {
                "chance_of_playing": 1.0,
                "status": "a",
                "price_millions": 8.5,
                "rotation_risk_score": 0.1,
                "minutes": 1800,
            },
            {
                "chance_of_playing": 0.5,
                "status": "d",
                "price_millions": 5.0,
                "rotation_risk_score": 0.4,
                "minutes": 300,
            },
        ]
    )
    states = model.predict_state_probabilities(df)
    row_sums = states.sum(axis=1).round(6)
    assert all(value == 1.0 for value in row_sums.tolist())


def test_expected_minutes_from_states_respects_state_weights():
    model = MinutesModel()
    states = pd.DataFrame(
        [
            {"START_90": 1.0, "START_60": 0.0, "SUB_30": 0.0, "SUB_10": 0.0, "BENCHED": 0.0, "DNP": 0.0},
            {"START_90": 0.0, "START_60": 0.0, "SUB_30": 0.5, "SUB_10": 0.5, "BENCHED": 0.0, "DNP": 0.0},
        ]
    )
    expected = model.expected_minutes_from_states(states)
    assert expected[0] == 90.0
    assert expected[1] == 17.5


def test_cache_keys_are_stable_and_prefix_scoped():
    key_one = make_cache_key("oracle_history", 123, "registered")
    key_two = make_cache_key("oracle_history", 123, "registered")
    key_three = make_cache_key("gw_intel", 123, "registered")
    assert key_one == key_two
    assert key_one != key_three
    assert key_one.startswith("cache:oracle_history:")
