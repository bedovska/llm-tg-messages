from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubjectId(str, Enum):
    ukrainian_veterans = "ukrainian_veterans"
    ukrainian_idps = "ukrainian_idps"
    ukrainian_families_of_mobilized = "ukrainian_families_of_mobilized"
    ukrainian_families_of_fallen = "ukrainian_families_of_fallen"
    ukrainian_families_of_missing = "ukrainian_families_of_missing"
    ukrainian_demobilized = "ukrainian_demobilized"
    ukrainian_draft_evaders = "ukrainian_draft_evaders"
    ukrainian_people_with_mobilization_deferment = (
        "ukrainian_people_with_mobilization_deferment"
    )
    ukrainian_residents_of_occupied_territories = (
        "ukrainian_residents_of_occupied_territories"
    )
    ukrainian_residents_of_frontline_regions = (
        "ukrainian_residents_of_frontline_regions"
    )
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
    ukrainian_women = "ukrainian_women"
    ukrainian_men = "ukrainian_men"
    ukrainian_lgbt_people = "ukrainian_lgbt_people"
    ukrainian_children = "ukrainian_children"
    ukrainian_elderly_people = "ukrainian_elderly_people"
    ukrainian_people_with_disabilities = "ukrainian_people_with_disabilities"
    ukrainian_military_personnel = "ukrainian_military_personnel"
    ukrainian_tcc_personnel = "ukrainian_tcc_personnel"
    ukrainian_police = "ukrainian_police"
    ukrainian_government_officials = "ukrainian_government_officials"
    foreign_government_officials = "foreign_government_officials"
    ukrainian_journalists = "ukrainian_journalists"
    ukrainian_teachers = "ukrainian_teachers"
    ukrainian_rescuers = "ukrainian_rescuers"
    ukrainian_hospital_medical_workers = "ukrainian_hospital_medical_workers"
    ukrainian_municipal_workers = "ukrainian_municipal_workers"
    ukrainian_volunteers = "ukrainian_volunteers"
    ukrainian_social_activists = "ukrainian_social_activists"
    migrant_workers_in_ukraine = "migrant_workers_in_ukraine"
    ukrainian_oligarchs = "ukrainian_oligarchs"
    ukrainian_low_income_people = "ukrainian_low_income_people"
    ukrainian_high_income_people = "ukrainian_high_income_people"
    ukrainian_unemployed_people = "ukrainian_unemployed_people"


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
    mention_terms: list[str] = Field(min_length=1)
    stance: Stance
    portrayal: list[Portrayal] = Field(min_length=1)
    descriptors: list[str]
    metaphors: list[str]
    narrative_claim: Optional[str]
    harm_types: list[HarmType]
    action_targeting_group: TargetAction
    counter_narrative: bool
    counter_narrative_claim: Optional[str]
    evidence: str = Field(min_length=1)

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
        return self
