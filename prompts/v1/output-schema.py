from enum import Enum
from typing import Optional

from pydantic import BaseModel

class MentionType(str, Enum):
    explicit = "explicit"
    implicit = "implicit"


class Stance(str, Enum):
    supportive = "supportive"
    neutral = "neutral"
    critical = "critical"
    hostile = "hostile"
    mixed = "mixed"


class Portrayal(str, Enum):
    neutral = "neutral"
    positive = "positive"
    heroizing = "heroizing"
    victimizing = "victimizing"
    stigmatizing = "stigmatizing"
    dehumanizing = "dehumanizing"
    threatening = "threatening"
    ridiculing = "ridiculing"
    delegitimizing = "delegitimizing"
    other = "other"


class HarmType(str, Enum):
    stigmatization = "stigmatization"
    dehumanization = "dehumanization"
    justification_of_discrimination = "justification_of_discrimination"
    justification_of_violence = "justification_of_violence"
    exclusion = "exclusion"
    undermining_trust = "undermining_trust"
    harassment = "harassment"
    other = "other"


class TargetAction(str, Enum):
    none = "none"
    vague_hostility = "vague_hostility"
    call_for_restriction = "call_for_restriction"
    call_for_exclusion = "call_for_exclusion"
    call_for_discrimination = "call_for_discrimination"
    call_for_violence = "call_for_violence"


class SubjectAnalysis(BaseModel):
    subject_id: str

    mention_type: MentionType
    mention_terms: list[str]

    stance: Stance
    portrayal: list[Portrayal]

    descriptors: list[str]
    metaphors: list[str]

    narrative_claim: Optional[str]

    harm_types: list[HarmType]
    action_targeting_group: TargetAction

    counter_narrative: bool
    counter_narrative_claim: Optional[str]

    evidence: str


class MessageAnalysis(BaseModel):
    relevant: bool
    subjects: list[SubjectAnalysis]
