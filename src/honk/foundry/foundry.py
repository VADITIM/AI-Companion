"""The Foundry: the craftsman that builds what Honk asks for. It has no will: it never runs unless a build request
passed the code gate, and it only ever returns a recipe of simple shapes that code checks before anything is placed.

    request (from a Resolve call) -> gate -> Foundry call -> check 1 (structure, one fix attempt) -> check 2 (review) -> place

Not done here (plan, section 8): rendering a screenshot in a headless browser for the reviews. Check 2 reviews the
parts list as text instead.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import config
from ..mind import schemas
from ..mind.client import MindError, OpenAI
from ..textsim import shorten, similarity

CHECKER = Path(__file__).with_name("check.mjs")
BANNED = re.compile(r"\b(sex|sexual|nude|naked|porn|erotic|genital|gore|gory|corpse|swastika)\w*", re.I)


def make_client(params, mind_client):
    f = params["foundry"]
    kind = f["provider"]
    key = os.environ.get("OPENROUTER_API_KEY") or _account_key()
    if kind == "stub":
        from ..stubs.fake_foundry import FakeFoundry
        return FakeFoundry()
    if kind == "openrouter" or (kind == "auto" and key):
        if not key:
            raise ValueError("foundry.provider is openrouter but no key is set (OPENROUTER_API_KEY or config/accounts.json)")
        return OpenAI(f["url"], f["model"], f["timeout_s"], key=key)
    return mind_client     # "local", or "auto" without a key: the mind's own model does the crafting


def _account_key():
    try:
        return json.loads((config.CONFIG / "accounts.json").read_text("utf-8")).get("openrouter", {}).get("key")
    except (OSError, ValueError, AttributeError):
        return None


def check_recipe(recipe, name, max_parts):
    """Static validation, then the world's own recipe checker. Returns {ok, hard, soft, recipe, radius}."""
    if not isinstance(recipe, dict) or not isinstance(recipe.get("parts"), list):
        return {"ok": False, "hard": ["the answer is not a recipe with a list of parts"], "soft": []}
    if not 3 <= len(recipe["parts"]) <= max_parts:
        return {"ok": False, "hard": [f"it has {len(recipe['parts'])} parts; use between 4 and {max_parts}"], "soft": []}
    if BANNED.search(json.dumps(recipe)) or BANNED.search(name or ""):
        return {"ok": False, "hard": ["it breaks the content rules"], "soft": [], "banned": True}
    node = shutil.which("node")
    if not node:
        return {"ok": False, "hard": ["the recipe checker needs node, which is not installed"], "soft": []}
    try:
        out = subprocess.run([node, str(CHECKER)], input=json.dumps({"recipe": recipe, "name": name, "maxParts": max_parts}),
                             capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout)
    except (subprocess.SubprocessError, ValueError) as e:
        return {"ok": False, "hard": [f"the recipe could not be checked ({e})"], "soft": []}


class Foundry:
    def __init__(self, client, params, db, sections, now=lambda: 0.0):
        self.client, self.p, self.db, self.sections, self.now = client, params, db, sections, now

    # ---------------------------------------------------------------- the gate (code, not the model)
    def busy(self):
        return bool(self.db.val("SELECT COUNT(*) FROM builds WHERE status IN ('queued', 'building')"))

    def gate(self, section_id, thing, cycle_targets=()):
        """Why this request may not go ahead, or '' when it may."""
        f, now = self.p["foundry"], self.now()
        if self.busy():
            return "the Foundry is already building something"
        why = self.sections.gate(section_id)
        if why:
            return why
        if len(thing.strip()) < 3:
            return "the request does not say what to build"
        if BANNED.search(thing):
            return "that breaks the content rules"
        hour = self.db.val("SELECT COUNT(*) FROM builds WHERE ts > ?", (now - 60,))
        day = self.db.val("SELECT COUNT(*) FROM builds WHERE ts > ?", (now - 1440,))
        if hour >= f["per_hour"] or day >= f["per_day"]:
            return "the build budget is used up for now"
        for old in self.db.all("SELECT thing FROM builds ORDER BY id DESC LIMIT ?", (int(self.p["mind"]["lockout_k"]),)):
            if similarity(old["thing"], thing) > 0.7:
                return "he asked for nearly the same thing a moment ago"
        return ""

    def request(self, section_id, thing, why, brief, question_id):
        return self.db.insert("builds", ts=self.now(), section_id=section_id, question_id=question_id, thing=shorten(thing, 80), why=shorten(why, 300),
                              brief=shorten(brief, 300), status="queued")

    # ---------------------------------------------------------------- the work
    def _ask(self, name, user, schema, tokens):
        return schemas.check(self.client.chat(name, config.art_rules(), user, schema, 0.7, tokens), schema)

    def process(self):
        """Build the oldest queued request. Returns the finished build row (status 'placed' or 'dropped'), or None if nothing waits."""
        b = self.db.one("SELECT * FROM builds WHERE status = 'queued' ORDER BY id LIMIT 1")
        if not b:
            return None
        self.db.update("builds", b["id"], status="building")
        s = self.sections.get(b["section_id"])
        ask = (f"The keeper asks for: {b['thing']}\nWhy: {b['why']}\nHow it should look and feel: {b['brief']}\n"
               f"It will stand in {s['name']}: {s['theme']}. What fits there: {s.get('things', 'anything')}.\nAnswer with the recipe as JSON.")
        max_parts = int(self.p["foundry"]["max_parts"])

        def drop(reason, **cols):
            self.db.update("builds", b["id"], status="dropped", drop_reason=shorten(reason, 300), **cols)
            return self.db.one("SELECT * FROM builds WHERE id = ?", (b["id"],))

        try:
            recipe = self._ask("foundry", ask, schemas.RECIPE, 2500)
            res = check_recipe(recipe, b["thing"], max_parts)
            if not res["ok"] and not res.get("banned"):     # check 1 failed: one chance to fix it
                fix = ask + "\n\nYour last recipe had these problems. Send the whole recipe again with them fixed:\n" + "\n".join(f"- {h}" for h in res["hard"]) + "\n\nYour last recipe:\n" + json.dumps(recipe)[:6000]
                recipe = self._ask("foundry_fix", fix, schemas.RECIPE, 2500)
                res = check_recipe(recipe, b["thing"], max_parts)
            if not res["ok"]:
                return drop("it did not hold together: " + "; ".join(res["hard"])[:200], qc1="failed: " + "; ".join(res["hard"])[:300])
            self.db.update("builds", b["id"], qc1="passed" + (": " + "; ".join(res["soft"])[:200] if res["soft"] else ""))
            if self.p["foundry"]["checks"] >= 2:            # check 2: does it look like what was asked for?
                listing = "\n".join(f"- {p['shape']} {p['color']}{' glowing' if p['glow'] else ''} at {p['pos']} size {p['scale']}" for p in res["recipe"]["parts"][:40])
                review = self._ask("foundry_review", f"The keeper asked for: {b['thing']}\nStyle: {b['brief']}\nThis is the finished object, part by part:\n{listing}\n"
                                   'Would someone recognise it as what was asked for, and does it follow the rules? JSON: {"ok": true or false, "reason": "one sentence"}', schemas.REVIEW, 150)
                if not review["ok"]:
                    return drop("it did not look like what he meant: " + shorten(review.get("reason", ""), 160), qc2="failed: " + shorten(review.get("reason", ""), 200))
                self.db.update("builds", b["id"], qc2="passed: " + shorten(review.get("reason", ""), 200))
        except (MindError, ValueError) as e:
            return drop(f"the Foundry could not finish it ({shorten(str(e), 120)})")
        spot = self.sections.spot(b["section_id"], min(3.5, res.get("radius", 1.5)))
        if not spot:
            return drop(f"there was no room left in {s['name']}")
        name = shorten(str(recipe.get("name") or b["thing"]), 60)
        self.db.update("builds", b["id"], status="placed", recipe_json=json.dumps(res["recipe"]), x=spot[0], z=spot[1], rot=spot[2], placed_ts=self.now(), name=name)
        return self.db.one("SELECT * FROM builds WHERE id = ?", (b["id"],))
