import datetime as dt
import unittest
import _bootstrap  # noqa
from danzaboss.cortex.app_profile import learn_profile, ScanFacts
from danzaboss.research.sources import Source, StubLane, MultiSourceCollector
from danzaboss.research.summarizer import StubSummarizer, ResearchResult
from danzaboss.research.proposal import Proposal, ProposalStatus
from danzaboss.research.throttle import ProposalThrottle, ThrottleConfig
from danzaboss.research.messaging import ConsoleChannel, parse_reply
from danzaboss.research.squad import ResearchSquad, SquadConfig


class TestCollector(unittest.TestCase):
    def test_newest_ranked_first_and_deduped(self):
        now = dt.datetime(2026, 7, 1)
        web = StubLane("web", [
            Source("u1", "old", published="2026-01-01"),
            Source("u2", "fresh", published="2026-06-28"),
        ])
        yt = StubLane("youtube", [Source("u2", "dupe", published="2026-06-28"),
                                  Source("u3", "mid", published="2026-05-01")])
        col = MultiSourceCollector([web, yt])
        got = col.collect("topic", now=now, limit=10)
        self.assertEqual([s.url for s in got], ["u2", "u3", "u1"])  # newest first
        self.assertEqual(len({s.url for s in got}), 3)              # deduped

    def test_lane_name_stamped(self):
        col = MultiSourceCollector([StubLane("web", [Source("u1")])])
        got = col.collect("t", now=dt.datetime(2026, 7, 1))
        self.assertEqual(got[0].lane, "web")


class TestThrottle(unittest.TestCase):
    def setUp(self):
        self.cfg = ThrottleConfig(max_per_day=2, allowed_hours=(9,), min_impact=60)
        self.thr = ProposalThrottle(self.cfg)
        self.at9 = dt.datetime(2026, 7, 1, 9, 0)

    def test_low_impact_blocked(self):
        p = Proposal(feature="f", title="t", rationale="r", impact=40)
        ok, why = self.thr.can_send(p, self.at9)
        self.assertFalse(ok); self.assertIn("threshold", why)

    def test_outside_window_blocked(self):
        p = Proposal(feature="f", title="t", rationale="r", impact=90)
        ok, why = self.thr.can_send(p, dt.datetime(2026, 7, 1, 13, 0))
        self.assertFalse(ok); self.assertIn("window", why)

    def test_daily_ceiling_enforced(self):
        p = Proposal(feature="f", title="t", rationale="r", impact=90)
        self.assertTrue(self.thr.can_send(p, self.at9)[0]); self.thr.record_sent(self.at9)
        self.assertTrue(self.thr.can_send(p, self.at9)[0]); self.thr.record_sent(self.at9)
        self.assertFalse(self.thr.can_send(p, self.at9)[0])  # 3rd blocked

    def test_ceiling_not_quota(self):
        # only one clears the impact bar -> only one selected, not padded to max
        cands = [Proposal(feature="f", title="hi", rationale="r", impact=90),
                 Proposal(feature="f", title="lo", rationale="r", impact=30)]
        sel = self.thr.select(cands, self.at9)
        self.assertEqual(len(sel), 1)

    def test_day_rolls_over(self):
        p = Proposal(feature="f", title="t", rationale="r", impact=90)
        self.thr.record_sent(self.at9); self.thr.record_sent(self.at9)
        next_day = dt.datetime(2026, 7, 2, 9, 0)
        self.assertTrue(self.thr.can_send(p, next_day)[0])  # reset


class TestMessaging(unittest.TestCase):
    def test_parse_reply(self):
        self.assertEqual(parse_reply("APPROVE prop_123"), (ProposalStatus.APPROVED.value, "prop_123"))
        self.assertEqual(parse_reply("DENY prop_9"), (ProposalStatus.DENIED.value, "prop_9"))
        self.assertEqual(parse_reply("garbage"), ("", ""))

    def test_console_channel_captures(self):
        ch = ConsoleChannel()
        ch.send(Proposal(feature="mixer", title="add sidechain", rationale="competitors do it"))
        self.assertIn("DANZA proposal", ch.outbox[0])


class TestSquadEndToEnd(unittest.TestCase):
    def test_full_cycle_is_app_agnostic_and_throttled(self):
        profile = learn_profile("noisemaker",
            ScanFacts(detected_features=[{"name": "mixer", "description": "multi-track"},
                                         {"name": "eq"}]),
            domain="audio tool", goals=["great mixer"], big_feature_names={"mixer"})
        lane = StubLane("web", [Source("https://blog/x", "fresh", published="2026-06-29")])
        squad = ResearchSquad(
            collector=MultiSourceCollector([lane]),
            summarizer=StubSummarizer(),
            throttle=ProposalThrottle(ThrottleConfig(max_per_day=2, allowed_hours=(9,), min_impact=60)),
            channel=ConsoleChannel(),
            cfg=SquadConfig(deep_only_big=True))
        sent = squad.run_cycle(profile, now=dt.datetime(2026, 7, 1, 9, 0))
        # only the big feature (mixer) researched; proposal sent via channel
        self.assertTrue(all(p.feature == "mixer" for p in sent))
        self.assertLessEqual(len(sent), 2)
        self.assertTrue(squad.channel.outbox)

    def test_nothing_sent_outside_window(self):
        profile = learn_profile("x", ScanFacts(detected_features=[{"name": "f"}]),
                                big_feature_names={"f"})
        squad = ResearchSquad(
            MultiSourceCollector([StubLane("web", [Source("u", published="2026-06-30")])]),
            StubSummarizer(),
            ProposalThrottle(ThrottleConfig(allowed_hours=(9,))),
            ConsoleChannel())
        sent = squad.run_cycle(profile, now=dt.datetime(2026, 7, 1, 15, 0))  # 3pm
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
