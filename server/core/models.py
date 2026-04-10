from typing import Optional, Literal

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=10000)
    context_ai: str = ""
    status: int = Field(0, ge=0, le=6)
    type: str = "base"
    checklist: dict = {}
    creator: Literal["human", "ai"] = "human"


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=10000)
    context_ai: Optional[str] = None
    status: Optional[int] = Field(None, ge=0, le=6)
    type: Optional[str] = None
    ai_notepad: Optional[str] = None
    checklist: Optional[dict] = None
    creator: Literal["human", "ai"] = "human"


class TaskStatusChange(BaseModel):
    status: int = Field(..., ge=0, le=6)
    creator: Literal["human", "ai"] = "human"


class TaskReorder(BaseModel):
    priority: int = 0


class MCPToolCall(BaseModel):
    name: str
    arguments: dict = {}
