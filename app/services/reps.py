"""Rep services: who the rep is, and the scoring preset they last chose."""

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import scoring
from app.db.models import Rep


class RepInfo(BaseModel):
    """A sales rep, as the UI shows them."""

    id: int
    name: str
    preset: str | None  # the preset they last chose; None until they pick one


def get_rep(session: Session, rep_id: int) -> RepInfo:
    """Return one rep.

    Raises:
        LookupError: No rep has this id.
    """
    rep = session.get(Rep, rep_id)
    if rep is None:
        raise LookupError(f"No rep with id {rep_id}")
    return RepInfo(id=rep.id, name=rep.name, preset=rep.preset)


def save_preset(session: Session, rep_id: int, preset: str) -> None:
    """Save the rep's chosen preset on their rep row, so their next visit starts on it. The caller commits.

    Raises:
        ValueError: The preset isn't one in config/scoring.yaml.
    """
    presets = scoring.load_scoring_config().presets
    if preset not in presets:
        raise ValueError(f"Unknown preset {preset!r}; choose from {', '.join(presets)}")
    session.execute(update(Rep).where(Rep.id == rep_id).values(preset=preset))
