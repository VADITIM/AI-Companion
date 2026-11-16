"""The only contract between the world and the mind.

Every message is a JSON string with a version, an id, a type and a payload. The two sides never touch each
other's objects: the in-process Bus below can be swapped for a socket to an external engine (Godot) without
changing either side.
"""
import itertools
import json
from collections import deque

VERSION = 1
TO_MIND = {"world.observation", "world.event", "creature.action_progress", "creature.action_completed",
           "system.heartbeat"}
TO_WORLD = {"creature.execute_action", "creature.cancel_action", "creature.state", "creature.speak",
            "system.heartbeat"}
_ids = itertools.count(1)


class ProtocolError(ValueError):
    pass


def encode(type_, payload, timestamp, allowed):
    if type_ not in allowed:
        raise ProtocolError(f"message type {type_!r} is not allowed in this direction")
    prefix = "evt" if allowed is TO_MIND else "cmd"
    return json.dumps({"protocol_version": VERSION, "message_id": f"{prefix}_{next(_ids):06d}", "type": type_,
                       "timestamp": round(timestamp, 2), "payload": payload})


def decode(raw, allowed):
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise ProtocolError(f"not JSON: {e}") from None
    if not isinstance(msg, dict) or msg.get("protocol_version") != VERSION:
        raise ProtocolError("wrong or missing protocol_version")
    if msg.get("type") not in allowed:
        raise ProtocolError(f"unexpected message type {msg.get('type')!r}")
    if not isinstance(msg.get("payload"), dict) or not isinstance(msg.get("message_id"), str):
        raise ProtocolError("payload must be an object and message_id a string")
    return msg


class Bus:
    """Two queues of encoded messages. `recent` keeps the last few for the developer dashboard."""

    def __init__(self):
        self._mind, self._world = deque(), deque()
        self.recent = deque(maxlen=40)

    def to_mind(self, type_, payload, timestamp):
        self._mind.append(encode(type_, payload, timestamp, TO_MIND))

    def to_world(self, type_, payload, timestamp):
        raw = encode(type_, payload, timestamp, TO_WORLD)
        self._world.append(raw)
        if type_ != "creature.state":
            self.recent.append(json.loads(raw))

    def push_raw_to_world(self, raw):
        self._world.append(raw)

    def drain_mind(self):
        while self._mind:
            msg = decode(self._mind.popleft(), TO_MIND)
            if msg["type"] != "world.observation":
                self.recent.append(msg)
            yield msg

    def drain_world(self):
        while self._world:
            yield decode(self._world.popleft(), TO_WORLD)
