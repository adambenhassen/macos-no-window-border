import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from windowstate import Actions, Tracker, Window, latest_line, parse_watch  # noqa: E402

PID = 500


def win(wid=1, maximized=True, shadow=True, pid=PID):
    return Window(wid, pid, shadow, maximized)


def settle(tracker, windows, start=0.0):
    """Run scans at start and start + 0.5 s; return the second scan's actions."""
    tracker.update(windows, start)
    return tracker.update(windows, start + 0.5)


class LatestLineTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(latest_line(b""), (None, b""))

    def test_partial_line_is_kept(self):
        self.assertEqual(latest_line(b"12:500:1"), (None, b"12:500:1"))

    def test_one_line(self):
        self.assertEqual(latest_line(b"12:500:1:0\n"), ("12:500:1:0", b""))

    def test_empty_line(self):
        self.assertEqual(latest_line(b"\n"), ("", b""))

    def test_newest_of_many_lines(self):
        self.assertEqual(
            latest_line(b"12:500:1:0\n12:500:0:1\n12:500:0:0\n"), ("12:500:0:0", b"")
        )

    def test_newest_complete_line_and_partial_rest(self):
        self.assertEqual(
            latest_line(b"12:500:1:0\n12:500:0:1\n12:50"), ("12:500:0:1", b"12:50")
        )

    def test_partial_line_completed_by_next_read(self):
        line, rest = latest_line(b"12:500:1:0\n13:5")
        self.assertEqual(line, "12:500:1:0")
        self.assertEqual(latest_line(rest + b"01:0:1\n"), ("13:501:0:1", b""))


class ParseWatchTest(unittest.TestCase):
    def test_parses_tokens(self):
        self.assertEqual(
            parse_watch("12:500:1:0 13:501:0:1\n"),
            [Window(12, 500, True, False), Window(13, 501, False, True)],
        )

    def test_empty_line(self):
        self.assertEqual(parse_watch("\n"), [])


class ApplyTest(unittest.TestCase):
    def test_waits_for_settle_then_applies(self):
        t = Tracker()
        self.assertTrue(t.update([win()], 0.0).empty())
        self.assertTrue(t.update([win()], 0.25).empty())
        acts = t.update([win()], 0.5)
        self.assertEqual(acts.apply, {PID: [1]})
        self.assertEqual(acts.tag, [])  # the queued corner call restores the shadow; tag next scan
        self.assertEqual(t.applied, {1: PID})

    def test_flicker_restarts_settle(self):
        t = Tracker()
        t.update([win()], 0.0)
        t.update([win(maximized=False)], 0.25)
        self.assertTrue(t.update([win()], 0.5).empty())
        self.assertEqual(t.update([win()], 1.0).apply, {PID: [1]})

    def test_never_touches_unmaximized_windows(self):
        t = Tracker()
        for now in (0.0, 0.5, 1.0, 5.0):
            self.assertTrue(t.update([win(maximized=False)], now).empty())

    def test_skip_pids(self):
        t = Tracker()
        self.assertTrue(t.update([win()], 0.0, skip_pids={PID}).empty())
        self.assertTrue(t.update([win()], 0.5, skip_pids={PID}).empty())
        self.assertEqual(t.applied, {})

    def test_groups_by_pid(self):
        t = Tracker()
        acts = settle(t, [win(1), win(2), win(3, pid=600)])
        self.assertEqual(acts.apply, {PID: [1, 2], 600: [3]})


class TagTest(unittest.TestCase):
    def test_tags_applied_window_with_shadow_and_backs_off(self):
        t = Tracker()
        settle(t, [win()])                                  # applied at 0.5
        self.assertEqual(t.update([win()], 0.75).tag, [1])  # shadow back: tag now
        self.assertEqual(t.update([win()], 1.0).tag, [])    # backoff 2 s
        self.assertEqual(t.update([win()], 2.75).tag, [1])  # 2 s later
        self.assertEqual(t.update([win()], 3.0).tag, [])    # backoff now 4 s
        self.assertEqual(t.update([win()], 6.75).tag, [1])

    def test_no_tag_when_shadow_already_gone(self):
        t = Tracker()
        settle(t, [win()])
        self.assertEqual(t.update([win(shadow=False)], 0.75).tag, [])


class RestoreTest(unittest.TestCase):
    def test_restores_after_settle(self):
        t = Tracker()
        settle(t, [win()])
        self.assertTrue(t.update([win(maximized=False)], 1.0).empty())
        acts = t.update([win(maximized=False)], 1.5)
        self.assertEqual(acts.restore, {PID: [1]})
        self.assertEqual(acts.untag, [1])
        self.assertEqual(t.applied, {})

    def test_does_not_untag_window_that_had_no_shadow(self):
        t = Tracker()
        settle(t, [win(shadow=False)])  # app turned its own shadow off before we applied
        acts = settle(t, [win(maximized=False, shadow=False)], 1.0)
        self.assertEqual(acts.restore, {PID: [1]})
        self.assertEqual(acts.untag, [])

    def test_missing_window_keeps_its_record(self):
        t = Tracker()
        settle(t, [win()])
        t.update([], 1.0)                                    # minimized or on another Space
        acts = settle(t, [win(maximized=False)], 2.0)        # back, no longer maximized
        self.assertEqual(acts.restore, {PID: [1]})

    def test_restore_all(self):
        t = Tracker()
        settle(t, [win(1), win(2, shadow=False), win(3, pid=600)])
        acts = t.restore_all()
        self.assertEqual(acts.restore, {PID: [1, 2], 600: [3]})
        self.assertEqual(acts.untag, [1, 3])
        self.assertEqual(t.applied, {})
        self.assertTrue(t.restore_all().empty())


def next_apply(tracker, start):
    """Scan the maximized window every 0.25 s from start until an apply comes out; return when."""
    now = start
    while not tracker.update([win()], now).apply:
        now += 0.25
    return now


class BusyTest(unittest.TestCase):
    def test_busy_apply_is_not_applied_and_waits_out_the_hold(self):
        t = Tracker()
        settle(t, [win()])                                    # apply emitted at 0.5
        self.assertEqual(t.hold(PID, [1], 0.5, restoring=False), 1)
        self.assertEqual(t.applied, {})
        for now in (0.75, 1.0, 1.25):                         # held until 1.5: no tag, no apply
            self.assertTrue(t.update([win()], now).empty())
        self.assertTrue(t.update([win()], 1.5).empty())       # hold over: settle again
        self.assertEqual(t.update([win()], 2.0).apply, {PID: [1]})

    def test_held_window_gets_no_actions_even_when_it_changes(self):
        t = Tracker()
        settle(t, [win()])
        t.hold(PID, [1], 0.5, restoring=False)
        for now in (0.75, 1.0, 1.25):
            self.assertTrue(t.update([win(maximized=False)], now).empty())

    def test_backoff_doubles_caps_and_resets_after_success(self):
        t = Tracker()
        now = next_apply(t, 0.0)
        delays = []
        for _ in range(7):
            delays.append(t.hold(PID, [1], now, restoring=False))
            later = next_apply(t, now + 0.25)
            self.assertEqual(later, now + delays[-1] + 0.5)  # hold, then the 0.5 s settle
            now = later
        self.assertEqual(delays, [1, 2, 4, 8, 16, 30, 30])
        t.update([win()], now + 0.25)                        # not busy: applied and seen
        acts = settle(t, [win(maximized=False)], now + 0.5)
        self.assertEqual(acts.restore, {PID: [1]})
        self.assertEqual(t.hold(PID, [1], now + 1.0, restoring=True), 1)

    def test_busy_restore_stays_applied_and_retries(self):
        t = Tracker()
        settle(t, [win()])
        acts = settle(t, [win(maximized=False)], 1.0)
        self.assertEqual((acts.restore, acts.untag), ({PID: [1]}, [1]))
        self.assertEqual(t.hold(PID, [1], 1.5, restoring=True), 1)
        self.assertEqual(t.applied, {1: PID})
        for now in (1.75, 2.0, 2.25):
            self.assertTrue(t.update([win(maximized=False)], now).empty())
        self.assertTrue(t.update([win(maximized=False)], 2.5).empty())
        acts = t.update([win(maximized=False)], 3.0)
        self.assertEqual(acts.restore, {PID: [1]})
        self.assertEqual(acts.untag, [])                     # cleared on the first try already
        self.assertEqual(t.applied, {})

    def test_remaximized_during_busy_restore_is_tagged_and_later_untagged(self):
        t = Tracker()
        settle(t, [win()])
        settle(t, [win(maximized=False)], 1.0)
        t.hold(PID, [1], 1.5, restoring=True)
        self.assertEqual(t.update([win()], 2.5).tag, [1])    # still applied; shadow is back
        acts = settle(t, [win(maximized=False)], 3.0)
        self.assertEqual((acts.restore, acts.untag), ({PID: [1]}, [1]))

    def test_restore_all_includes_windows_held_for_restore_only(self):
        t = Tracker()
        settle(t, [win(1), win(2)])
        settle(t, [win(1, maximized=False), win(2), win(3)], 1.0)  # restore 1, apply 3
        t.hold(PID, [1], 1.5, restoring=True)
        t.hold(PID, [3], 1.5, restoring=False)               # never applied: nothing to undo
        acts = t.restore_all()
        self.assertEqual(sorted(acts.restore[PID]), [1, 2])
        self.assertEqual(acts.untag, [2])                    # 1 was untagged by the busy restore


class ActionsTest(unittest.TestCase):
    def test_empty(self):
        self.assertTrue(Actions().empty())
        self.assertFalse(Actions(tag=[1]).empty())


if __name__ == "__main__":
    unittest.main()
