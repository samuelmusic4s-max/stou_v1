from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4
from datetime import date, datetime


def new_id():
    return str(uuid4())


class SourceType(StrEnum):
    Pdf = "Pdf"
    Md = "Md"
    Txt = "Txt"
    Video = "Video"


@dataclass
class Source:
    project_id: str
    name: str
    path: str
    source_type: SourceType
    published_date: date
    id: str = field(default_factory=new_id)


@dataclass
class Chunk:
    project_id: str
    source_id: str
    text: str
    position: int
    heading: str
    embedding: list[float] = field(default_factory=list)
    id: str = field(default_factory=new_id)


@dataclass
class Question:
    prompt: str
    correct_index: int
    related_block_id: str
    id: str = field(default_factory=new_id)
    options: list[str] = field(default_factory=list)


@dataclass
class QuizAttempt:
    score: int
    total: int
    taken_at: datetime
    wrong_block_ids: list[str] = field(default_factory=list)


class TaskStatus(StrEnum):
    Pending = "Pending"
    In_Progress = "In_Progress"
    Done = "Done"


@dataclass
class Task:
    title: str
    description: str
    status: TaskStatus
    due_at: datetime
    id: str = field(default_factory=new_id)
    estimated_minutes: int = 30


@dataclass
class TopicNode:
    title: str
    description: str = ""
    id: str = field(default_factory=new_id)
    children: list[TopicNode] = field(default_factory=list)

    def add_child(self, child: TopicNode) -> TopicNode | None:
        if not isinstance(child, TopicNode):
            return None
        self.children.append(child)
        return child

    def flatten(self) -> list[TopicNode]:
        nodes = [self]
        for node in self.children:
            if node is not None:
                nodes.extend(node.flatten())
        return nodes


class BlockType(StrEnum):
    Title = "Title"
    Text = "Text"
    Code = "Code"
    Video = "Video"


@dataclass
class BlockNode:
    topic_id: str
    block_type: BlockType
    content: str
    start_time: int | None = None
    end_time: int | None = None
    next: BlockNode | None = None
    id: str = field(default_factory=new_id)
    source_ids: list[str] = field(default_factory=list)


@dataclass
class BlockLinkedList:
    head: BlockNode | None = None

    def append(self, node: BlockNode) -> None:
        if not isinstance(node, BlockNode):
            return None
        node.next = None
        if self.head is None:
            self.head = node
        else:
            current_node = self.head
            if current_node is node:
                return None
            while current_node.next is not None:
                if current_node.next is node:
                    return None
                current_node = current_node.next
            current_node.next = node

    def insert_after(self, target_id: str, new_node: BlockNode) -> bool:
        if self.head is None or not isinstance(new_node, BlockNode):
            return False
        probe = self.head
        while probe is not None:
            if probe is new_node:
                return False
            probe = probe.next
        current_index = self.head
        while current_index is not None:
            if current_index.id == target_id:
                new_node.next = current_index.next
                current_index.next = new_node
                return True
            current_index = current_index.next
        return False

    def to_list(self) -> list[BlockNode]:
        nodes = []
        seen: set[int] = set()
        current_node = self.head
        while current_node is not None and id(current_node) not in seen:
            seen.add(id(current_node))
            nodes.append(current_node)
            current_node = current_node.next
        return nodes


@dataclass
class Lesson:
    title: str
    markdown: str
    created_at: datetime = field(default_factory=datetime.now)
    source_ids: list[str] = field(default_factory=list)
    id: str = field(default_factory=new_id)


@dataclass
class Project:
    name: str
    created_at: datetime = field(default_factory=datetime.now)
    outline: TopicNode | None = None
    id: str = field(default_factory=new_id)
    blocks: BlockLinkedList = field(default_factory=BlockLinkedList)
    sources: list[Source] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    attempts: list[QuizAttempt] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    lessons: list[Lesson] = field(default_factory=list)
