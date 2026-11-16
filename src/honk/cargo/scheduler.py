"""The cargo window: the only time the internet exists for Honk.

    CLOSED --(gap timer)--> ARRIVED --(unpacked)--> OPEN --(window - closing)--> CLOSING --> CLOSED

The gap is measured from the moment the last window closed. All times are simulated minutes. The scheduler is plain
state plus a tick; it never touches the network itself: the gateway asks it whether the hatch is open.
"""
import random

CLOSED, ARRIVED, OPEN, CLOSING = "closed", "arrived", "open", "closing"


class Scheduler:
    def __init__(self, params, state=None, rnd=None):
        self.p = params
        self.rnd = rnd or random.Random()
        c = params["cargo"]
        self.s = state or {"state": CLOSED, "since": 0.0, "next": self.rnd.uniform(c["gap_min"], c["gap_max"]) * 0.2, "window": 0,
                           "ledger": c["ledger"], "opened": None}

    @property
    def state(self):
        return self.s["state"]

    @property
    def window(self):
        return self.s["window"]

    @property
    def ledger(self):
        return self.s["ledger"]

    @property
    def story_over(self):
        """The last counted cargo has landed. What still arrives are unexplained signals."""
        return self.s["ledger"] <= 0

    def web_allowed(self, kind="research"):
        """Feeds may be fetched while a cargo is unpacked; research needs the hatch open."""
        if kind == "feed":
            return self.state in (ARRIVED, OPEN, CLOSING)
        return self.state in (OPEN, CLOSING)

    def minutes_left(self, now):
        c = self.p["cargo"]
        if self.state == CLOSED:
            return max(0.0, self.s["next"] - now)
        if self.state in (OPEN, CLOSING):
            return max(0.0, self.s["opened"] + c["window_min"] - now)
        return max(0.0, self.s["since"] + c["arrived_max_min"] - now)

    def tick(self, now, unpacked=False, asleep=False):
        """Move the state machine on. Returns the transitions that happened, oldest first: 'arrived', 'open', 'closing', 'closed'."""
        c, out = self.p["cargo"], []
        while True:
            st = self.state
            if st == CLOSED and now >= self.s["next"]:
                self.s.update(state=ARRIVED, since=self.s["next"], window=self.s["window"] + 1)
                if self.s["ledger"] > 0:
                    self.s["ledger"] -= 1
                out.append("arrived")
            elif st == ARRIVED and not asleep and (unpacked or now >= self.s["since"] + c["arrived_max_min"]):
                self.s.update(state=OPEN, since=now, opened=now)
                out.append("open")
            elif st == OPEN and now >= self.s["opened"] + c["window_min"] - c["closing_min"]:
                self.s.update(state=CLOSING, since=self.s["opened"] + c["window_min"] - c["closing_min"])
                out.append("closing")
            elif st == CLOSING and now >= self.s["opened"] + c["window_min"]:
                end = self.s["opened"] + c["window_min"]
                gap = self.rnd.uniform(c["gap_min"], c["gap_max"])
                self.s.update(state=CLOSED, since=end, next=(end if c["gap_from"] == "close" else self.s["opened"]) + gap, opened=None)
                out.append("closed")
            else:
                return out
            unpacked = False
