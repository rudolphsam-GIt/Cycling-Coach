"""
Keep intervals.icu and the TrainingPeaks calendar in step when planned rides are removed in the
app. Moves and edits are picked up by the next sync; a removal has nothing left to sync, so it is
passed on straight away. Best effort: a service that can't be reached never blocks a removal.
"""
from __future__ import annotations


def remove_everywhere(workout_ids: list[int]) -> None:
    """Take these rides off every service they were sent to."""
    from auth import intervals, trainingpeaks
    ids = [int(w) for w in workout_ids if w is not None]
    if not ids:
        return
    for service in (intervals, trainingpeaks):
        try:
            service.remove(ids)
        except Exception:
            pass
