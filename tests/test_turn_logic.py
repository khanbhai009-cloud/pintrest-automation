import mastermind.node_cmo as node_cmo


def test_decide_turn_flips_account_1_to_account_2(monkeypatch):
    monkeypatch.setattr(node_cmo, "load_style_tracker", lambda: {"next_turn": "account_1"})
    saved = {}

    def fake_save(tracker):
        saved.update(tracker)

    monkeypatch.setattr(node_cmo, "save_style_tracker", fake_save)

    assert node_cmo._decide_turn() == "account_1"
    assert saved == {"next_turn": "account_2"}


def test_decide_turn_flips_account_2_to_account_1(monkeypatch):
    monkeypatch.setattr(node_cmo, "load_style_tracker", lambda: {"next_turn": "account_2"})
    saved = {}

    def fake_save(tracker):
        saved.update(tracker)

    monkeypatch.setattr(node_cmo, "save_style_tracker", fake_save)

    assert node_cmo._decide_turn() == "account_2"
    assert saved == {"next_turn": "account_1"}
