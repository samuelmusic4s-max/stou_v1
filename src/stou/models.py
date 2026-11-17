from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4
from datetime import date


def new_id():
    return str(uuid4())


class SourceType(Enum):
    pdf = 1
    md = 2
    txt = 3
    video = 4


@dataclass
class Source:
    project_id: str
    name: str
    path: str
    source_type: SourceType
    published_date: date
    id: str = field(default_factory=new_id())
