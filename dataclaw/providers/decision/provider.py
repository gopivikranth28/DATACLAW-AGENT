"""DecisionProvider protocol and the shared question/answer models.

A decision model answers typed questions about a ``state`` (text or a JSON
object) instead of chatting: pick one of several options (``choice``), rate
against ordered levels (``score``) or answer yes/no (``boolean``).  Backends
are TypeSafe's Jev (calibrated probabilities) and an LLM fallback that
answers the same schema through ``structured_output``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator

QuestionKind = Literal["choice", "score", "boolean"]

# Jev accepts 1-255 choices and 1-10 score levels; the LLM fallback uses the
# same limits so a question means the same thing on either backend.
MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10


class DecisionError(RuntimeError):
    """A decision backend could not answer (transport, API or parse failure)."""


class DecisionConfigurationError(ValueError):
    """The decision backend cannot be built from the current configuration."""


class DecisionQuestion(BaseModel):
    """One question about the state.

    ``options`` are the choices for ``choice`` and the ordered level
    descriptions for ``score`` (the answer is the level index, starting at
    0).  ``boolean`` questions take no options.  ``option_descriptions``
    optionally explains choices (``{option: description}``).
    """

    id: str = Field(min_length=1, max_length=128)
    kind: QuestionKind
    prompt: str = Field(min_length=1)
    options: list[str] | None = None
    option_descriptions: dict[str, str] | None = None

    @model_validator(mode="after")
    def _check_options(self) -> "DecisionQuestion":
        options = self.options or []
        if self.kind == "boolean":
            if options:
                raise ValueError(f"boolean question {self.id!r} takes no options")
            self.options = None
            return self
        if not options:
            raise ValueError(f"{self.kind} question {self.id!r} needs options")
        if any(not str(o).strip() for o in options):
            raise ValueError(f"question {self.id!r} has an empty option")
        if self.kind == "choice":
            if len(set(options)) != len(options):
                raise ValueError(f"choice question {self.id!r} has duplicate options")
            if len(options) > MAX_CHOICE_OPTIONS:
                raise ValueError(f"choice question {self.id!r} has more than {MAX_CHOICE_OPTIONS} options")
        elif len(options) > MAX_SCORE_LEVELS:
            raise ValueError(f"score question {self.id!r} has more than {MAX_SCORE_LEVELS} levels")
        unknown = set(self.option_descriptions or {}) - set(options)
        if unknown:
            raise ValueError(f"question {self.id!r} describes unknown options: {sorted(unknown)}")
        return self


class DecisionResult(BaseModel):
    """The answer to one question.

    ``answer`` is the chosen option (choice), the expected level as a float
    (score) or a bool (boolean).  ``probabilities`` maps each option / level
    index / "true"/"false" to its probability when the backend provides a
    distribution; ``None`` otherwise.  ``calibrated`` is False when
    ``confidence`` is a model's self-report rather than a probability.
    """

    id: str
    answer: str | float | bool
    probabilities: dict[str, float] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    calibrated: bool = True


@runtime_checkable
class DecisionProvider(Protocol):
    """Answers typed questions about a state."""

    name: str

    async def decide(
        self,
        state: str | dict[str, Any],
        questions: list[DecisionQuestion],
    ) -> list[DecisionResult]:
        """Return one result per question, in question order.

        Raises ``DecisionError`` when the backend cannot answer.
        """
        ...
