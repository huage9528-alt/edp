"""decisions 请求/响应模型（设计文档附录 B.5 逐字段，EDP-018 最小版）。

- POST /decisions/cases：question/context/options/risk_level/source_type/
  source_id/evidence_ids → 201 {case_id, case_no, status, created_at}；
- GET /decisions/cases：列表简投影 + 游标分页（status/risk_level 过滤）；
- GET /decisions/cases/{case_id}：详情含 evidence_refs（links join 投影）+
  decisions（决策记录列表）；
- POST /decisions/cases/{case_id}/records：Human-Only → 201 {decision_id,
  case_id, decision_time, case_status}。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["P0", "P1", "P2", "P3"]
CaseStatus = Literal["OPEN", "DECIDED", "CANCELLED"]
DecisionType = Literal["HUMAN", "AI_SUGGESTED"]


class CaseOptionIn(BaseModel):
    """案例选项（B.5 options[{key,label}]）。"""

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=255)


class CaseCreateRequest(BaseModel):
    """POST /decisions/cases 请求（B.5）。"""

    question: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    options: list[CaseOptionIn] = Field(default_factory=list, max_length=50)
    risk_level: RiskLevel | None = None
    source_type: str | None = Field(default=None, max_length=128)
    source_id: str | None = Field(default=None, max_length=255)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)


class CaseCreatedResponse(BaseModel):
    """POST /decisions/cases 响应（201）。"""

    case_id: UUID
    case_no: str
    status: str
    created_at: datetime


class CaseListItem(BaseModel):
    """GET /decisions/cases 列表项（B.5 简投影）。"""

    model_config = ConfigDict(from_attributes=True)

    case_id: UUID
    case_no: str | None
    question: str
    risk_level: str | None
    status: str
    created_at: datetime


class EvidenceRefItem(BaseModel):
    """案例关联证据引用（B.5 evidence_refs[{evidence_id, checksum, source_system}]）。"""

    evidence_id: UUID
    checksum: str
    source_system: str


class DecisionItem(BaseModel):
    """决策记录项（B.5 decisions[]）。"""

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID
    chosen_option: str
    decision_type: str
    decided_by: str
    decision_time: datetime
    comment: str | None


class CaseDetailResponse(BaseModel):
    """GET /decisions/cases/{case_id} 响应（B.5）。"""

    case_id: UUID
    question: str
    context: dict[str, Any]
    options: list[dict[str, Any]]
    risk_level: str | None
    status: str
    evidence_refs: list[EvidenceRefItem] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)


class DecisionCreateRequest(BaseModel):
    """POST /decisions/cases/{case_id}/records 请求（B.5；Human-Only）。"""

    chosen_option: str = Field(min_length=1, max_length=128)
    decision_type: DecisionType = "HUMAN"
    comment: str | None = Field(default=None, max_length=2000)


class DecisionCreatedResponse(BaseModel):
    """POST /decisions/cases/{case_id}/records 响应（201）。"""

    decision_id: UUID
    case_id: UUID
    decision_time: datetime
    case_status: str
