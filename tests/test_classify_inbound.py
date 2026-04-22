from agent.sms_gateway import classify_inbound


def test_stop_variants():
    for s in ["STOP", "stop", " Stop ", "UNSUBSCRIBE", "cancel", "QUIT", "end"]:
        assert classify_inbound(s) == "stop", s


def test_help_variants():
    for s in ["HELP", "help", "INFO"]:
        assert classify_inbound(s) == "help", s


def test_regular():
    for s in ["hi", "tell me more", "stop by anytime"]:
        # Note "stop by anytime" is NOT a bare STOP; must be regular
        assert classify_inbound(s) == "message", s


def test_empty():
    assert classify_inbound("") == "message"
    assert classify_inbound(None) == "message"  # type: ignore
