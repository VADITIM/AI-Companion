"""The action registry and the validator. Nothing reaches the world unless it is in here and passes the checks."""
from .world import SIZE

# name -> what the step must carry. "named" actions use the capability of the same name on the target.
ACTIONS = {
    "move_to": {"needs": "target_or_position"},
    "inspect": {"needs": "target"},
    "eat": {"needs": "target", "capability": "eat"},
    "sleep": {"needs": "optional_target", "capability": "sleep"},
    "play": {"needs": "target", "capability": "play"},
    "create": {"needs": "target", "capability": "create"},
    "interact": {"needs": "target", "capability": None},   # any other capability the object has shown
    "explore": {"needs": "position"},                      # compiled to move_to before it is sent
    "rest": {"needs": None},
    "call_out": {"needs": None},
    "wait": {"needs": None},
    "look_around": {"needs": None},
}
NAMED = {"eat", "sleep", "play", "create"}


def step_for(capability, target):
    """The action step that uses `capability` on `target`."""
    if capability in NAMED:
        return {"action": capability, "target": target}
    if capability == "inspect":
        return {"action": "inspect", "target": target}
    return {"action": "interact", "target": target, "capability": capability}


def validate(step, know, needs=None, busy=False):
    """Return (ok, reason). `know` is what the creature knows about objects: it cannot act on what it has not found."""
    if not isinstance(step, dict):
        return False, "not_an_action"
    spec = ACTIONS.get(step.get("action"))
    if not spec:
        return False, "unknown_action"
    if busy:
        return False, "already_acting"
    target, pos, want = step.get("target"), step.get("position"), spec["needs"]
    if want in ("target", "target_or_position", "optional_target") and target is not None:
        k = know.get(target)
        if not k:
            return False, "unknown_target"
        if k.get("gone"):
            return False, "target_gone"
        cap = spec.get("capability", "") if "capability" in spec else ""
        if step["action"] == "interact":
            cap = step.get("capability")
            if not isinstance(cap, str):
                return False, "missing_capability"
        if cap and cap not in k.get("caps", []):
            return False, "capability_not_known"
    elif want == "target":
        return False, "missing_target"
    if want == "position" or (want == "target_or_position" and target is None):
        ok = (isinstance(pos, (list, tuple)) and len(pos) == 2
              and all(isinstance(v, (int, float)) and 0 <= v <= SIZE for v in pos))
        if not ok:
            return False, "bad_position"
    if step["action"] == "sleep" and needs is not None and needs.v["fatigue"] < 0.2:
        return False, "not_tired"
    return True, ""
