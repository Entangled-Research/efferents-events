from efferents.cluster.limits import RateLimiter


def test_sliding_window():
    now = [0.0]
    rl = RateLimiter(2, 60, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    assert rl.allow("b")
    now[0] = 61
    assert rl.allow("a")
    rl.reset()
    assert rl.allow("a") and rl.allow("a")
    assert RateLimiter(0).allow("anything")
