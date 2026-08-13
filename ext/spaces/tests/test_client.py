# Copyright (c) 2024- Datalayer, Inc.
#
# BSD 3-Clause License

"""Turning a name an agent typed into one notebook, or a question."""

from __future__ import annotations

from jupyter_mcp_spaces.spaces import resolve


NOTEBOOKS = [
    {"uid": "ntb-1", "name": "sales-forecast.ipynb", "notebook_name": "sales_forecast", "space": "Personal"},
    {"uid": "ntb-2", "name": "sales-forecast-v2.ipynb", "notebook_name": "sales_forecast_v2", "space": "Team"},
    {"uid": "ntb-3", "name": "churn.ipynb", "notebook_name": "churn", "space": "Personal"},
]


class TestResolve:
    def test_a_uid_wins_outright(self):
        assert resolve(NOTEBOOKS, "ntb-2") == [NOTEBOOKS[1]]

    def test_an_exact_name_beats_a_partial_one(self):
        # Both notebooks contain "sales-forecast"; only one *is* it. Without
        # this the exact match is buried among its own prefixes.
        assert resolve(NOTEBOOKS, "sales-forecast.ipynb") == [NOTEBOOKS[0]]

    def test_the_extension_is_optional(self):
        assert resolve(NOTEBOOKS, "churn") == [NOTEBOOKS[2]]

    def test_a_partial_name_returns_every_candidate(self):
        # Two matches, and the caller is asked rather than one being picked:
        # guessing is how an agent edits the wrong notebook.
        assert len(resolve(NOTEBOOKS, "sales")) == 2

    def test_case_does_not_matter(self):
        assert resolve(NOTEBOOKS, "CHURN.IPYNB") == [NOTEBOOKS[2]]

    def test_nothing_matches_nothing(self):
        assert resolve(NOTEBOOKS, "does-not-exist") == []

    def test_an_empty_name_matches_nothing(self):
        # Not "everything": an empty argument is a mistake, and answering it
        # with the whole list invites opening an arbitrary notebook.
        assert resolve(NOTEBOOKS, "") == []


class TestKindLivesInTheSdk:
    """`is_notebook` is a property of the model, not of this extension."""

    def test_the_model_answers_it(self):
        from datalayer_core.models.space import ItemModel

        assert ItemModel.from_response({"uid": "1", "type_s": "notebook"}).is_notebook()
        assert not ItemModel.from_response({"uid": "2", "type_s": "cell"}).is_notebook()
