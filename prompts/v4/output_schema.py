from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubjectId(str, Enum):
    veterans = "veterans"
    idps = "idps"
    families_of_mobilized = "families_of_mobilized"
    families_of_fallen = "families_of_fallen"
    families_of_missing = "families_of_missing"
    demobilized = "demobilized"
    draft_evaders = "draft_evaders"
    residents_of_occupied_territories = "residents_of_occupied_territories"
    residents_of_frontline_regions = "residents_of_frontline_regions"
    ukrainians_abroad = "ukrainians_abroad"
    roma = "roma"
    crimean_tatars = "crimean_tatars"
    jews = "jews"
    russians = "russians"
    russian_speaking_ukrainians = "russian_speaking_ukrainians"
    other_ethnic_minorities = "other_ethnic_minorities"
    orthodox_christians = "orthodox_christians"
    ukrainian_orthodox_church_moscow_patriarchate = (
        "ukrainian_orthodox_church_moscow_patriarchate"
    )
    orthodox_church_of_ukraine = "orthodox_church_of_ukraine"
    greek_catholics = "greek_catholics"
    roman_catholics = "roman_catholics"
    protestants = "protestants"
    muslims = "muslims"
    other_religious_groups = "other_religious_groups"
    women = "women"
    men = "men"
    lgbt_people = "lgbt_people"
    children = "children"
    elderly_people = "elderly_people"
    people_with_disabilities = "people_with_disabilities"
    military_personnel = "military_personnel"
    tcc_personnel = "tcc_personnel"
    police = "police"
    government_officials = "government_officials"
    foreign_government_officials = "foreign_government_officials"
    journalists = "journalists"
    teachers = "teachers"
    rescuers = "rescuers"
    hospital_medical_workers = "hospital_medical_workers"
    municipal_workers = "municipal_workers"
    volunteers = "volunteers"
    social_activists = "social_activists"
    migrant_workers = "migrant_workers"
    oligarchs = "oligarchs"
    low_income_people = "low_income_people"
    high_income_people = "high_income_people"
    unemployed_people = "unemployed_people"


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


class SubjectAnalysis(StrictModel):
    subject_id: SubjectId
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

    @model_validator(mode="after")
    def validate_consistency(self):
        if Portrayal.neutral in self.portrayal and len(self.portrayal) > 1:
            raise ValueError("neutral portrayal cannot be combined with others")
        if self.counter_narrative != (self.counter_narrative_claim is not None):
            raise ValueError(
                "counter_narrative_claim must be set exactly when "
                "counter_narrative is true"
            )
        return self


class MessageAnalysis(StrictModel):
    relevant: bool
    subjects: list[SubjectAnalysis]

    @model_validator(mode="after")
    def validate_relevance(self):
        if self.relevant != bool(self.subjects):
            raise ValueError("relevant must be true exactly when subjects is non-empty")
        subject_ids = [subject.subject_id for subject in self.subjects]
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("each subject may appear only once")
        return self
