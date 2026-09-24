"""Unit tests for managed-seat turn-gate accounting (elimination-aware)."""


def managed_gate_is_full(active_seats, done):
	"""Mirror of civ4ai_managed_gate_is_full without Civ4 runtime."""
	if not active_seats:
		return True
	for seat in active_seats:
		if seat not in done:
			return False
	return True


def test_gate_full_when_all_alive_seats_done():
	assert managed_gate_is_full([1, 2, 4], {1, 2, 4}) is True
	assert managed_gate_is_full([1, 2, 4], {1, 2, 3, 4}) is True


def test_gate_not_full_until_last_alive_seat():
	assert managed_gate_is_full([1, 2, 4], {1, 2}) is False
	assert managed_gate_is_full([1, 2, 4], {1, 2, 3}) is False


def test_gate_full_when_no_alive_managed_seats():
	assert managed_gate_is_full([], {1, 2, 3, 4}) is True


def test_expected_count_tracks_elimination():
	active = [1, 2, 4]
	done = {1, 2, 4}
	assert len(active) == 3
	assert managed_gate_is_full(active, done) is True
