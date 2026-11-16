"""The vault: what Honk keeps of humanity. It has a fixed number of slots, so keeping is choosing.

Stored per item: his own note (why he kept it), a short attributed quote, the source link and tags. Never the page.
Items are never deleted: a released item leaves the shelves but stays in the table with the reason he gave.
"""
from ..textsim import shorten


class Vault:
    def __init__(self, db, params):
        self.db, self.p = db, params

    def size(self):
        shelves = self.db.val("SELECT COUNT(*) FROM builds WHERE status = 'placed' AND section_id = 'vault'") or 0
        return int(self.p["vault"]["slots"] + self.p["vault"]["shelf_bonus"] * shelves)

    def used(self):
        return self.db.val("SELECT COUNT(*) FROM vault WHERE state = 'kept'") or 0

    def full(self):
        return self.used() >= self.size()

    def items(self, state="kept"):
        return self.db.all("SELECT * FROM vault WHERE state = ? ORDER BY kept_ts DESC", (state,))

    def weakest(self, n=3):
        """The kept things he cares least about, oldest first among equals: the candidates when something has to go."""
        return self.db.all("SELECT * FROM vault WHERE state = 'kept' ORDER BY interest, kept_ts LIMIT ?", (n,))

    def keep(self, item_id, title, note, quote, url, tags, interest, now):
        if self.full():
            raise ValueError("the vault is full")
        return self.db.insert("vault", section_id="vault", item_id=item_id, title=shorten(title, 120), note=shorten(note, 240), quote=shorten(quote, 220),
                              url=str(url)[:300], tags=",".join(tags), interest=interest, kept_ts=now)

    def release(self, vault_id, reason, now):
        row = self.db.one("SELECT * FROM vault WHERE id = ? AND state = 'kept'", (vault_id,))
        if not row:
            return None
        self.db.update("vault", vault_id, state="released", released_ts=now, released_reason=shorten(reason, 240))
        return row
