"""Hybrid parser service for reliable command interpretation.

This parser combines:
1. Candidate-consensus parsing over ASR N-best alternatives.
2. Deterministic regex routing with weighted scoring and schema checks.

The goal is maximizing execution accuracy while minimizing unnecessary
clarification turns.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.services.parser.config import (
    ASR_ALTERNATIVE_DECAY,
    CLARIFY_MIN_CONFIDENCE,
    CLARIFY_MIN_MARGIN,
    COMMAND_LIKE_SIGNAL_MIN,
    COMMAND_OVERRIDE_CONFIDENCE,
    COMMAND_PREFIX_PATTERN,
    COMMAND_SIGNAL_PATTERNS,
    CONTROL_INTENTS,
    FILLER_PATTERNS,
    INTENT_BASE_WEIGHTS,
    INTENT_KEYWORDS,
    INTENT_REQUIRED_PARAMS,
    MAX_ASR_ALTERNATIVES,
    MIN_INTENT_SCORE,
    NARRATIVE_PATTERNS,
    QUERY_NOISE_PATTERNS,
    RAW_PATTERNS,
    STRONG_COMMAND_SIGNAL,
    SYNONYMS,
)
from app.services.parser.models import CommandContext, CommandIntent

logger = logging.getLogger(__name__)


@dataclass
class _TranscriptCandidate:
    """Single candidate transcript in the parser consensus set."""

    raw_text: str
    normalized_text: str
    weight: float
    source: str


@dataclass
class _CandidateParse:
    """Per-candidate parse output before cross-candidate consensus."""

    candidate: _TranscriptCandidate
    intent: str
    parameters: dict[str, Any]
    confidence: float
    command_signal: float
    score_margin: float
    intent_scores: dict[str, float]


class CommandParser:
    """Hybrid parser tuned for integration toolchain command reliability."""

    def __init__(self) -> None:
        self.patterns = self._load_patterns()
        self.synonyms = self._load_synonyms()
        self.intent_keywords = self._load_intent_keywords()
        self.query_noise_patterns = self._load_query_noise_patterns()

        self._command_prefix_pattern = re.compile(COMMAND_PREFIX_PATTERN, re.IGNORECASE)
        self._command_signal_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in COMMAND_SIGNAL_PATTERNS
        ]
        self._narrative_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in NARRATIVE_PATTERNS
        ]

    def _load_patterns(self) -> dict[str, list[re.Pattern[str]]]:
        compiled_patterns: dict[str, list[re.Pattern[str]]] = {}
        for intent, patterns_list in RAW_PATTERNS.items():
            compiled_patterns[intent] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns_list
            ]
        return compiled_patterns

    def _load_synonyms(self) -> dict[str, str]:
        return dict(SYNONYMS)

    def _load_intent_keywords(self) -> dict[str, list[str]]:
        return {intent: list(keywords) for intent, keywords in INTENT_KEYWORDS.items()}

    def _load_query_noise_patterns(self) -> list[str]:
        return list(QUERY_NOISE_PATTERNS)

    def _clean_query_value(self, value: str) -> str:
        """Clean noise phrases from extracted entity values."""
        cleaned = value
        for pattern in self.query_noise_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        cleaned = cleaned.replace("?", "").replace('"', "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,")
        return cleaned

    def normalize_text(self, text: str) -> str:
        """Normalize text for robust pattern matching across ASR variants."""
        normalized = text.lower().strip()
        normalized = normalized.replace("’", "'")
        normalized = re.sub(r"\s+", " ", normalized)

        for pattern in FILLER_PATTERNS:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

        # Keep "like this/that" while removing filler usage of "like".
        normalized = re.sub(
            r"\blike\b(?!\s+(?:this|that))", "", normalized, flags=re.IGNORECASE
        )

        # Apply longer synonym phrases first.
        synonym_items = sorted(
            self.synonyms.items(), key=lambda item: len(item[0]), reverse=True
        )
        for synonym, canonical in synonym_items:
            normalized = re.sub(
                r"\b" + re.escape(synonym) + r"\b", canonical, normalized
            )

        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _build_candidates(
        self, text: str, alternatives: Optional[list[str]]
    ) -> list[_TranscriptCandidate]:
        """Build weighted transcript candidates for consensus parsing."""
        candidates: list[_TranscriptCandidate] = []
        seen: set[str] = set()

        def add_candidate(raw_text: str, weight: float, source: str) -> None:
            cleaned_raw = raw_text.strip()
            if not cleaned_raw:
                return
            normalized = self.normalize_text(cleaned_raw)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            candidates.append(
                _TranscriptCandidate(
                    raw_text=cleaned_raw,
                    normalized_text=normalized,
                    weight=weight,
                    source=source,
                )
            )

        add_candidate(text, 1.0, "primary")

        alt_list = alternatives or []
        for index, alternative in enumerate(alt_list[:MAX_ASR_ALTERNATIVES]):
            weight = max(0.35, 1.0 - (index + 1) * ASR_ALTERNATIVE_DECAY)
            add_candidate(alternative, weight, f"alternative_{index + 1}")

        logger.debug(
            "Built parser transcript candidates",
            extra={
                "primary_text": text,
                "alternatives_count": len(alt_list),
                "candidate_count": len(candidates),
            },
        )
        return candidates

    def _compute_command_signal(self, normalized_text: str) -> float:
        """Score whether text is likely imperative command language."""
        if not normalized_text:
            return 0.0

        score = 0.18
        if self._command_prefix_pattern.search(normalized_text):
            score += 0.50

        signal_hits = sum(
            1
            for pattern in self._command_signal_patterns
            if pattern.search(normalized_text)
        )
        score += min(0.22, signal_hits * 0.11)

        if re.search(
            r"\b(?:play|pause|resume|next|previous|queue|playlist|album)\b",
            normalized_text,
        ):
            score += 0.08

        narrative_hits = sum(
            1 for pattern in self._narrative_patterns if pattern.search(normalized_text)
        )
        if narrative_hits:
            score -= min(0.32, 0.16 * narrative_hits)

        # Penalize descriptive first-person phrasing unless command prefix exists.
        if re.search(
            r"\b(?:i|we)\b", normalized_text
        ) and not self._command_prefix_pattern.search(normalized_text):
            score -= 0.12

        return max(0.0, min(score, 1.0))

    def _score_pattern_match(self, normalized_text: str, match: re.Match[str]) -> float:
        text_length = max(len(normalized_text), 1)
        coverage = len(match.group(0)) / text_length

        score = 0.54 + (coverage * 0.24)
        if match.start() == 0:
            score += 0.08
        if match.groupdict():
            named_filled = sum(1 for value in match.groupdict().values() if value)
            score += 0.07 + min(0.06, named_filled * 0.02)
        if match.group(0).strip() == normalized_text:
            score += 0.05

        return max(0.0, min(score, 1.0))

    def _score_intent(
        self,
        normalized_text: str,
        intent: str,
        command_signal: float,
    ) -> tuple[float, dict[str, Any]]:
        """Return score and extracted parameters for a candidate intent."""
        best_pattern_score = 0.0
        best_entities: dict[str, Any] = {}

        for pattern in self.patterns.get(intent, []):
            match = pattern.search(normalized_text)
            if not match:
                continue

            pattern_score = self._score_pattern_match(normalized_text, match)
            if pattern_score > best_pattern_score:
                best_pattern_score = pattern_score
                best_entities = {
                    key: value.strip()
                    for key, value in match.groupdict().items()
                    if value and value.strip()
                }

        keyword_hits = 0
        for keyword in self.intent_keywords.get(intent, []):
            if keyword in normalized_text:
                keyword_hits += 1
        keyword_score = min(0.21, keyword_hits * 0.07)

        intent_bias = INTENT_BASE_WEIGHTS.get(intent, 0.0)
        command_boost = 0.06 if command_signal >= 0.65 else 0.0

        score = best_pattern_score + keyword_score + intent_bias + command_boost

        # Penalize broad artist intent when richer intents are likely.
        if intent == "play_artist":
            artist_value = str(best_entities.get("artist", "")).strip()
            if not artist_value:
                score -= 0.08
            if any(marker in artist_value for marker in ("playlist", "album", "track")):
                score -= 0.14

        if (
            intent == "resume"
            and normalized_text != "play"
            and "resume" not in normalized_text
        ):
            # Prevent accidental "resume" on regular play commands.
            score -= 0.10

        return max(0.0, min(score, 1.0)), best_entities

    def _required_params(self, intent: str) -> tuple[str, ...]:
        return INTENT_REQUIRED_PARAMS.get(intent, ())

    def _has_required_params(self, intent: str, parameters: dict[str, Any]) -> bool:
        required = self._required_params(intent)
        if not required:
            return True
        return all(bool(parameters.get(key)) for key in required)

    def _parse_candidate(self, candidate: _TranscriptCandidate) -> _CandidateParse:
        """Parse a single candidate transcript into intent and parameters."""
        normalized_text = candidate.normalized_text
        command_signal = self._compute_command_signal(normalized_text)

        intent_scores: dict[str, float] = {}
        extracted_entities: dict[str, dict[str, Any]] = {}

        for intent in self.patterns:
            score, entities = self._score_intent(
                normalized_text, intent, command_signal
            )
            intent_scores[intent] = score
            extracted_entities[intent] = entities

        ranked = sorted(intent_scores.items(), key=lambda item: item[1], reverse=True)
        top_intent, top_score = ranked[0] if ranked else ("unknown", 0.0)
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = max(0.0, top_score - second_score)

        if top_score < MIN_INTENT_SCORE:
            logger.debug(
                "Candidate intent below minimum score",
                extra={
                    "candidate_text": candidate.raw_text,
                    "top_intent": top_intent,
                    "top_score": round(top_score, 4),
                },
            )
            return _CandidateParse(
                candidate=candidate,
                intent="unknown",
                parameters={},
                confidence=max(0.0, command_signal * 0.35),
                command_signal=command_signal,
                score_margin=margin,
                intent_scores=intent_scores,
            )

        parameters = dict(extracted_entities.get(top_intent, {}))

        for key, value in list(parameters.items()):
            if key in {"track", "artist", "album", "playlist", "device"}:
                parameters[key] = self._clean_query_value(str(value))

        if (
            top_intent in {"set_volume", "volume_up", "volume_down"}
            and "level" not in parameters
        ):
            numbers = re.findall(r"\d+", normalized_text)
            if numbers:
                parameters["level"] = int(numbers[0])

        has_required_params = self._has_required_params(top_intent, parameters)

        confidence = (top_score * 0.64) + (margin * 0.21) + (command_signal * 0.15)
        if has_required_params:
            confidence += 0.05
        else:
            confidence -= 0.08

        confidence = max(0.0, min(confidence, 1.0))

        logger.debug(
            "Parsed candidate",
            extra={
                "candidate_text": candidate.raw_text,
                "normalized_text": normalized_text,
                "intent": top_intent,
                "confidence": round(confidence, 4),
                "command_signal": round(command_signal, 4),
                "score_margin": round(margin, 4),
                "parameters": parameters,
            },
        )

        return _CandidateParse(
            candidate=candidate,
            intent=top_intent,
            parameters=parameters,
            confidence=confidence,
            command_signal=command_signal,
            score_margin=margin,
            intent_scores=intent_scores,
        )

    def _merge_candidate_parameters(
        self,
        intent: str,
        candidate_parses: list[_CandidateParse],
        fallback_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge missing required params from supporting parses of same intent."""
        merged = dict(fallback_parameters)
        required = self._required_params(intent)

        # Reconcile required fields across candidates by weighted support.
        for field_name in required:
            values_by_raw: dict[str, float] = {}
            values_by_canonical: dict[str, float] = {}

            for parse in candidate_parses:
                if parse.intent != intent:
                    continue
                raw_value = parse.parameters.get(field_name)
                if raw_value is None:
                    continue
                value = str(raw_value).strip()
                if not value:
                    continue

                support = parse.confidence * parse.candidate.weight
                values_by_raw[value] = values_by_raw.get(value, 0.0) + support
                canonical = re.sub(r"[^a-z0-9]", "", value.lower())
                if canonical:
                    values_by_canonical[canonical] = (
                        values_by_canonical.get(canonical, 0.0) + support
                    )

            if not values_by_raw:
                continue

            if values_by_canonical:
                canonical_choice = max(
                    values_by_canonical.items(), key=lambda item: item[1]
                )[0]
                raw_candidates = [
                    value
                    for value in values_by_raw
                    if re.sub(r"[^a-z0-9]", "", value.lower()) == canonical_choice
                ]
            else:
                raw_candidates = list(values_by_raw.keys())

            # Prefer compact forms for equivalent canonicals (e.g. \"stargazing\"
            # over \"star gazing\") while retaining support weighting.
            raw_candidates.sort(
                key=lambda value: (
                    value.count(" "),
                    -values_by_raw.get(value, 0.0),
                    len(value),
                )
            )
            merged[field_name] = raw_candidates[0]

        # Fill any remaining missing required fields from top-down support.
        missing = [name for name in required if not merged.get(name)]
        if missing:
            for parse in candidate_parses:
                if parse.intent != intent:
                    continue
                for field_name in list(missing):
                    value = parse.parameters.get(field_name)
                    if value:
                        merged[field_name] = value
                        missing.remove(field_name)
                if not missing:
                    break

        return merged

    def _select_consensus_parse(self, parses: list[_CandidateParse]) -> _CandidateParse:
        """Select consensus parse across weighted transcript candidates."""
        if not parses:
            empty_candidate = _TranscriptCandidate(
                raw_text="",
                normalized_text="",
                weight=1.0,
                source="empty",
            )
            return _CandidateParse(
                candidate=empty_candidate,
                intent="unknown",
                parameters={},
                confidence=0.0,
                command_signal=0.0,
                score_margin=0.0,
                intent_scores={},
            )

        intent_support: dict[str, float] = {}
        for parse in parses:
            support = parse.candidate.weight * max(parse.confidence, 0.01)
            intent_support[parse.intent] = (
                intent_support.get(parse.intent, 0.0) + support
            )

        ranked_support = sorted(
            intent_support.items(), key=lambda item: item[1], reverse=True
        )
        top_intent, top_support = ranked_support[0]
        second_support = ranked_support[1][1] if len(ranked_support) > 1 else 0.0

        total_support = sum(intent_support.values())
        support_ratio = (top_support / total_support) if total_support > 0 else 0.0

        top_intent_parses = [parse for parse in parses if parse.intent == top_intent]
        top_intent_parses.sort(
            key=lambda parse: (
                parse.confidence * parse.candidate.weight,
                parse.command_signal,
                parse.score_margin,
            ),
            reverse=True,
        )
        best_parse = top_intent_parses[0]

        merged_parameters = self._merge_candidate_parameters(
            top_intent,
            top_intent_parses,
            best_parse.parameters,
        )

        confidence = (best_parse.confidence * 0.67) + (support_ratio * 0.33)
        confidence += 0.05 if (top_support - second_support) >= 0.12 else 0.0
        confidence = max(0.0, min(confidence, 1.0))

        score_margin = max(best_parse.score_margin, top_support - second_support)

        logger.info(
            "Consensus parse selected",
            extra={
                "intent": top_intent,
                "confidence": round(confidence, 4),
                "support_ratio": round(support_ratio, 4),
                "support_margin": round(top_support - second_support, 4),
                "candidate_count": len(parses),
            },
        )

        return _CandidateParse(
            candidate=best_parse.candidate,
            intent=top_intent,
            parameters=merged_parameters,
            confidence=confidence,
            command_signal=max(parse.command_signal for parse in top_intent_parses),
            score_margin=score_margin,
            intent_scores=best_parse.intent_scores,
        )

    def parse_command(
        self,
        text: str,
        context: Optional[CommandContext] = None,
        alternatives: Optional[list[str]] = None,
    ) -> CommandIntent:
        """Parse command text with N-best candidate consensus."""
        candidates = self._build_candidates(text, alternatives)
        parses = [self._parse_candidate(candidate) for candidate in candidates]
        consensus = self._select_consensus_parse(parses)

        parameters = dict(consensus.parameters)

        if context:
            parameters = self._apply_context(parameters, consensus.intent, context)

        requires_clarification = self._needs_clarification(
            intent=consensus.intent,
            parameters=parameters,
            confidence=consensus.confidence,
            command_signal=consensus.command_signal,
            score_margin=consensus.score_margin,
        )

        command_like = (
            consensus.intent != "unknown"
            and consensus.command_signal >= COMMAND_LIKE_SIGNAL_MIN
            and consensus.confidence >= COMMAND_OVERRIDE_CONFIDENCE
            and not requires_clarification
        )

        logger.info(
            "Final parser result",
            extra={
                "intent": consensus.intent,
                "confidence": round(consensus.confidence, 4),
                "requires_clarification": requires_clarification,
                "command_signal": round(consensus.command_signal, 4),
                "score_margin": round(consensus.score_margin, 4),
                "command_like": command_like,
            },
        )

        return CommandIntent(
            intent=consensus.intent,
            parameters=parameters,
            confidence=consensus.confidence,
            requires_clarification=requires_clarification,
            raw_text=text,
            alternatives=list(alternatives or []),
            parser_meta={
                "command_signal": consensus.command_signal,
                "score_margin": consensus.score_margin,
                "candidate_count": len(candidates),
                "source": consensus.candidate.source,
                "command_like": command_like,
            },
        )

    def _apply_context(
        self, parameters: dict[str, Any], intent: str, context: CommandContext
    ) -> dict[str, Any]:
        """Apply conversation context to fill in missing parameters."""
        if context.is_expired():
            logger.info("Context expired for user %s, resetting", context.user_id)
            context.reset()
            return parameters

        if intent == "play_another_by_artist":
            if context.last_artist:
                parameters["artist"] = context.last_artist
                parameters["_original_intent"] = intent
                parameters["_context_resolved"] = True
            else:
                parameters["_needs_clarification"] = True

        elif intent == "play_more_like_this":
            if context.last_track and context.last_artist:
                parameters["reference_track"] = context.last_track
                parameters["reference_artist"] = context.last_artist
                parameters["_original_intent"] = intent
                parameters["_context_resolved"] = True
            else:
                parameters["_needs_clarification"] = True

        elif intent == "play_from_same_album":
            if context.last_album and context.last_artist:
                parameters["album"] = context.last_album
                parameters["artist"] = context.last_artist
                parameters["_original_intent"] = intent
                parameters["_context_resolved"] = True
            else:
                parameters["_needs_clarification"] = True

        elif (
            intent == "play_track"
            and not parameters.get("artist")
            and context.last_artist
        ):
            parameters["artist"] = context.last_artist
            parameters["_context_resolved"] = True

        elif (
            intent == "play_album"
            and not parameters.get("artist")
            and context.last_artist
        ):
            parameters["artist"] = context.last_artist
            parameters["_context_resolved"] = True

        if context.active_device_id:
            parameters["device_id"] = context.active_device_id

        return parameters

    def _needs_clarification(
        self,
        intent: str,
        parameters: dict[str, Any],
        confidence: float,
        command_signal: float,
        score_margin: float,
    ) -> bool:
        """Apply clarification policy tuned for high precision with low churn."""
        if intent == "unknown":
            return True

        if parameters.get("_needs_clarification"):
            return True

        if not self._has_required_params(intent, parameters):
            return True

        if intent in CONTROL_INTENTS and command_signal >= 0.45:
            return False

        if confidence >= 0.56:
            return False

        if confidence >= CLARIFY_MIN_CONFIDENCE and score_margin >= CLARIFY_MIN_MARGIN:
            return False

        if (
            command_signal >= STRONG_COMMAND_SIGNAL
            and confidence >= CLARIFY_MIN_CONFIDENCE
            and score_margin >= 0.02
        ):
            return False

        return True


command_parser = CommandParser()
