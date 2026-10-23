# 경보 API 입력 스키마와 이름 규칙 (명세서 3.1)

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Zone = Literal["loading_bay", "distillation", "confined_tank"]

# 템플릿 문구용 표시명. 화면 표시명은 P4 가 따로 매핑한다
ZONE_NAMES: dict[str, str] = {
    "loading_bay": "출하장",
    "distillation": "증류탑",
    "confined_tank": "밀폐공간·탱크",
}

# 물질 키 목록은 P1 이 docs/data_sources.md 에서 확정한다. 여기 없는 키도 형식만 맞으면 받는다
SUBSTANCE_NAMES: dict[str, str] = {
    "propane": "프로판",
    "hydrogen_sulfide": "황화수소",
    "sulfur_dioxide": "이산화황",
    "ammonia": "암모니아",
    "chlorine": "염소",
}


class AlarmCreate(BaseModel):
    zone: Zone
    substance: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$",
                           description="영문 snake_case 물질 키 (예: propane)")
    stage: int = Field(ge=1, le=3, description="1 주의 · 2 경고 · 3 위험")
    note: str | None = Field(default=None, max_length=200)


class HeadcountIn(BaseModel):
    checked: int = Field(ge=0, le=10000)
    total: int = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def _checked_le_total(self):
        if self.checked > self.total:
            raise ValueError("checked 는 total 보다 클 수 없습니다.")
        return self


class ClearIn(BaseModel):
    note: str | None = Field(default=None, max_length=200)
