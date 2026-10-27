"""Small Mamdani fuzzy inference system (no third-party fuzzy dependency).

Inputs are a face similarity score (0..100) and *binary* fingerprint evidence.
The R307 only reports match / no-match through this firmware, so the binary
value is fuzzified as a crisp No Match / Match; no sensor confidence is
invented.

Inference steps (all exposed through ``FuzzyTrace`` for explanation/audit):
  1. fuzzification   - memberships of the crisp inputs in their linguistic sets
  2. rule evaluation - antecedent strength = min() of the antecedent memberships
  3. implication     - each rule clips its output set at its antecedent strength
  4. aggregation     - max() over all clipped output sets
  5. defuzzification - centroid over the integer universe 0..100
  6. decision        - ACCEPT only if the centroid >= the configured threshold

Every rule that supports acceptance requires fingerprint Match AND a High face
score, so missing or invalid evidence can never reach the accepting region
(invalid inputs raise ValueError instead of being guessed).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

UNIVERSE = tuple(range(101))


class FingerprintEvidence(Enum):
    NO_MATCH = 0
    MATCH = 1


# --- membership functions -------------------------------------------------------

def _trap(x: float, a: float, b: float, c: float, d: float) -> float:
    """Trapezoid (a,b,c,d); a triangle is b == c, a left/right shoulder repeats an end point."""
    if x < a or x > d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if x < b:
        return (x - a) / (b - a)
    return (d - x) / (d - c)


@dataclass(frozen=True)
class FaceSets:
    """Trapezoid parameters (a, b, c, d) of the Low / Medium / High face-score sets."""
    low: tuple[float, float, float, float] = (0, 0, 0, 55)
    medium: tuple[float, float, float, float] = (35, 60, 60, 85)
    high: tuple[float, float, float, float] = (65, 100, 100, 100)

    def __post_init__(self) -> None:
        for name in ("low", "medium", "high"):
            params = getattr(self, name)
            if len(params) != 4 or any(not math.isfinite(p) for p in params):
                raise ValueError(f"{name} face set needs four finite parameters")
            if not (0 <= params[0] <= params[1] <= params[2] <= params[3] <= 100):
                raise ValueError(f"{name} face set must satisfy 0 <= a <= b <= c <= d <= 100")

    @classmethod
    def anchored(cls, face_threshold: float, ramp: float = 10.0) -> "FaceSets":
        """Sets positioned around a *calibrated* face threshold T.

        Low ends at T, and High starts rising at T and is fully High at T+ramp,
        so a face score below T can never contribute High membership.
        """
        if not math.isfinite(face_threshold) or not 0 < face_threshold < 100:
            raise ValueError("anchoring needs a face threshold strictly between 0 and 100")
        if not math.isfinite(ramp) or ramp <= 0:
            raise ValueError("ramp must be positive")
        t = float(face_threshold)
        top = min(100.0, t + ramp)
        return cls(low=(0, 0, 0, t),
                   medium=(max(0.0, t - 20.0), t, t, top),
                   high=(t, top, 100, 100))


# Output sets (a, b, c, d) over the 0..100 authentication-score universe.
OUTPUT_SETS: dict[str, tuple[float, float, float, float]] = {
    "low": (0, 0, 0, 40),
    "medium": (25, 50, 50, 75),
    "high": (60, 80, 80, 95),
    "very_high": (85, 100, 100, 100),
}
# "medium" is kept as a defined set for display; no rule currently drives it.


@dataclass(frozen=True)
class Rule:
    rule_id: str
    fingerprint: str          # "match" or "no_match"
    face: str | None          # "low" / "medium" / "high", or None = any face score
    output: str
    text: str


RULES: tuple[Rule, ...] = (
    Rule("R1", "no_match", None, "low", "IF fingerprint is No Match THEN authentication is Low"),
    Rule("R2", "match", "low", "low", "IF fingerprint is Match AND face is Low THEN authentication is Low"),
    Rule("R3", "match", "medium", "low", "IF fingerprint is Match AND face is Medium THEN authentication is Low"),
    Rule("R4", "match", "high", "high", "IF fingerprint is Match AND face is High THEN authentication is High"),
    Rule("R5", "match", "high", "very_high", "IF fingerprint is Match AND face is High THEN authentication is Very High"),
)


# --- results ----------------------------------------------------------------------

@dataclass(frozen=True)
class RuleActivation:
    rule_id: str
    text: str
    strength: float
    output_set: str

    @property
    def fired(self) -> bool:
        return self.strength > 0.0


@dataclass(frozen=True)
class FuzzyTrace:
    face_score: float
    fingerprint: str
    face_memberships: dict[str, float]
    fingerprint_memberships: dict[str, float]
    rules: tuple[RuleActivation, ...]
    output_strengths: dict[str, float]     # max rule strength per output set (clipping level)
    universe: tuple[int, ...]
    aggregated: tuple[float, ...]          # aggregated membership at each universe point
    centroid: float
    threshold: float
    decision: str

    def rule_rows(self) -> list[dict]:
        return [{"rule": r.rule_id, "if/then": r.text, "activation": round(r.strength, 4),
                 "clips output set": r.output_set, "fired": r.fired} for r in self.rules]

    def curve_rows(self) -> dict[str, list[float]]:
        """Aggregated output curve plus the threshold marker, ready for a chart."""
        return {"aggregated membership": list(self.aggregated)}


@dataclass(frozen=True)
class FuzzyResult:
    score: float
    decision: str
    trace: FuzzyTrace | None = None


# --- public membership helpers (kept for the UI and tests) ---------------------------

def _check_face_score(score: float) -> None:
    if isinstance(score, bool) or not isinstance(score, (int, float)) \
            or not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("face_score must be a finite number from 0 to 100")


def face_memberships(score: float, sets: FaceSets | None = None) -> dict[str, float]:
    _check_face_score(score)
    sets = sets or FaceSets()
    return {"low": _trap(score, *sets.low), "medium": _trap(score, *sets.medium),
            "high": _trap(score, *sets.high)}


def fingerprint_memberships(evidence: FingerprintEvidence) -> dict[str, float]:
    if not isinstance(evidence, FingerprintEvidence):
        raise ValueError("fingerprint evidence must be a FingerprintEvidence value")
    return {"no_match": 1.0 if evidence is FingerprintEvidence.NO_MATCH else 0.0,
            "match": 1.0 if evidence is FingerprintEvidence.MATCH else 0.0}


# --- engine -------------------------------------------------------------------------

class FuzzyEngine:
    """Mamdani rules map a face score and binary fingerprint evidence to a 0..100 score."""

    def __init__(self, threshold: float = 75.0, face_sets: FaceSets | None = None):
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) \
                or not math.isfinite(threshold) or not 0 <= threshold <= 100:
            raise ValueError("threshold must be from 0 to 100")
        self.threshold = float(threshold)
        self.face_sets = face_sets or FaceSets()
        self._out_curves = {name: tuple(_trap(x, *params) for x in UNIVERSE)
                            for name, params in OUTPUT_SETS.items()}
        self._boundary_cache: float | None | str = "unset"

    @classmethod
    def for_settings(cls, threshold: float, face_threshold: float | None = None,
                     anchor_face_sets: bool = False, ramp: float = 10.0) -> "FuzzyEngine":
        """Default sets, or sets anchored to a calibrated face threshold when requested."""
        if anchor_face_sets and face_threshold is not None:
            return cls(threshold, FaceSets.anchored(face_threshold, ramp))
        return cls(threshold)

    def _infer(self, face_score: float, fingerprint: FingerprintEvidence):
        fm = face_memberships(face_score, self.face_sets)
        pm = fingerprint_memberships(fingerprint)
        activations = []
        for rule in RULES:
            strength = pm[rule.fingerprint]
            if rule.face is not None:
                strength = min(strength, fm[rule.face])
            activations.append(RuleActivation(rule.rule_id, rule.text, strength, rule.output))
        aggregated = tuple(
            max(min(a.strength, self._out_curves[a.output_set][i]) for a in activations)
            for i in range(len(UNIVERSE)))
        denominator = sum(aggregated)
        if denominator == 0:
            raise ValueError("fuzzy system produced no output")
        centroid = sum(x * m for x, m in zip(UNIVERSE, aggregated)) / denominator
        return fm, pm, tuple(activations), aggregated, centroid

    def evaluate(self, face_score: float, fingerprint: FingerprintEvidence) -> FuzzyResult:
        fm, pm, activations, aggregated, centroid = self._infer(face_score, fingerprint)
        decision = "ACCEPT" if centroid >= self.threshold else "DENY"
        strengths: dict[str, float] = {}
        for a in activations:
            strengths[a.output_set] = max(strengths.get(a.output_set, 0.0), a.strength)
        trace = FuzzyTrace(float(face_score), fingerprint.name, fm, pm, activations, strengths,
                           UNIVERSE, aggregated, centroid, self.threshold, decision)
        return FuzzyResult(centroid, decision, trace)

    def accept_boundary(self, step: float = 0.5) -> float | None:
        """Lowest face score (scanned in ``step`` increments) that yields ACCEPT with a
        fingerprint Match, or None if no face score does. Computed, not assumed."""
        if self._boundary_cache != "unset" and step == 0.5:
            return self._boundary_cache  # type: ignore[return-value]
        result: float | None = None
        n = int(round(100 / step))
        for i in range(n + 1):
            s = round(i * step, 6)
            try:
                centroid = self._infer(s, FingerprintEvidence.MATCH)[4]
            except ValueError:
                continue
            if centroid >= self.threshold:
                result = s
                break
        if step == 0.5:
            self._boundary_cache = result
        return result
