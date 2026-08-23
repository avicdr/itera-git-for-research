import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import String, Text, ForeignKey, Integer, DateTime, Boolean, UniqueConstraint, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid
from pgvector.sqlalchemy import Vector
from .base import Base, UUIDMixin, TimestampMixin

class ArtifactType(str, Enum): DOCUMENT="DOCUMENT"; PDF="PDF"; CHAT_EXPORT="CHAT_EXPORT"
class ArtifactStatus(str, Enum): UPLOADING="UPLOADING"; PROCESSING="PROCESSING"; INDEXING="INDEXING"; READY="READY"; FAILED="FAILED"
class Scope(str, Enum): WORKSPACE="WORKSPACE"; CHAT="CHAT"

class User(UUIDMixin, TimestampMixin, Base):
    __tablename__="users"; name: Mapped[str]=mapped_column(String(120)); email: Mapped[str]=mapped_column(String(255), unique=True)
class Workspace(UUIDMixin, TimestampMixin, Base):
    __tablename__="workspaces"; name: Mapped[str]=mapped_column(String(200)); description: Mapped[str|None]=mapped_column(Text); archived: Mapped[bool]=mapped_column(Boolean, default=False); created_by: Mapped[uuid.UUID]=mapped_column(Uuid, ForeignKey("users.id"))
class WorkspaceMember(UUIDMixin, TimestampMixin, Base):
    __tablename__="workspace_members"; __table_args__=(UniqueConstraint("workspace_id","user_id"),); workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); user_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); role: Mapped[str]=mapped_column(String(30),default="editor")
class Artifact(UUIDMixin, TimestampMixin, Base):
    __tablename__="artifacts"; __table_args__=(Index("ix_artifact_workspace", "workspace_id"),)
    workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); name: Mapped[str]=mapped_column(String(255)); original_filename: Mapped[str]=mapped_column(String(255)); artifact_type: Mapped[str]=mapped_column(String(30)); mime_type: Mapped[str]=mapped_column(String(120)); scope: Mapped[str]=mapped_column(String(20),default=Scope.WORKSPACE.value); chat_id: Mapped[uuid.UUID|None]=mapped_column(Uuid,ForeignKey("research_chats.id")); status: Mapped[str]=mapped_column(String(20),default=ArtifactStatus.UPLOADING.value); created_by: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); deleted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class ArtifactVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__="artifact_versions"; __table_args__=(UniqueConstraint("artifact_id","version_number"),)
    artifact_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifacts.id")); version_number: Mapped[int]=mapped_column(Integer); storage_path: Mapped[str]=mapped_column(String(600)); content_hash: Mapped[str]=mapped_column(String(64)); canonical_text: Mapped[str]=mapped_column(Text,default=""); editor_json: Mapped[dict|None]=mapped_column(JSON); created_by: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id"))
class Commit(UUIDMixin, TimestampMixin, Base):
    __tablename__="commits"; __table_args__=(Index("ix_commit_workspace_created","workspace_id","created_at"),)
    workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); author_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); message: Mapped[str]=mapped_column(String(500)); short_hash: Mapped[str]=mapped_column(String(12),unique=True)
class CommitParent(UUIDMixin, Base):
    __tablename__="commit_parents"; __table_args__=(UniqueConstraint("commit_id","parent_id"),); commit_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("commits.id")); parent_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("commits.id"))
class CommitArtifactVersion(UUIDMixin, Base):
    __tablename__="commit_artifact_versions"; __table_args__=(UniqueConstraint("commit_id","artifact_id"),); commit_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("commits.id")); artifact_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifacts.id")); artifact_version_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifact_versions.id"))
class Branch(UUIDMixin, TimestampMixin, Base):
    __tablename__="branches"; __table_args__=(UniqueConstraint("workspace_id","name"),); workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); name: Mapped[str]=mapped_column(String(120)); head_commit_id: Mapped[uuid.UUID|None]=mapped_column(Uuid,ForeignKey("commits.id")); created_by: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); is_protected: Mapped[bool]=mapped_column(Boolean,default=False)
class Merge(UUIDMixin, TimestampMixin, Base):
    __tablename__="merges"; workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); source_branch_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("branches.id")); target_branch_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("branches.id")); status: Mapped[str]=mapped_column(String(30),default="PENDING"); merge_commit_id: Mapped[uuid.UUID|None]=mapped_column(Uuid,ForeignKey("commits.id")); created_by: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id"))
class MergeConflict(UUIDMixin, TimestampMixin, Base):
    __tablename__="merge_conflicts"; merge_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("merges.id")); artifact_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifacts.id")); base_text: Mapped[str]=mapped_column(Text); target_text: Mapped[str]=mapped_column(Text); source_text: Mapped[str]=mapped_column(Text); resolved_text: Mapped[str|None]=mapped_column(Text); resolved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class ResearchChat(UUIDMixin, TimestampMixin, Base):
    __tablename__="research_chats"; workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); title: Mapped[str]=mapped_column(String(200)); created_by: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); active_branch_id: Mapped[uuid.UUID|None]=mapped_column(Uuid,ForeignKey("branches.id"))
class ChatMessage(UUIDMixin, TimestampMixin, Base):
    __tablename__="chat_messages"; chat_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("research_chats.id")); role: Mapped[str]=mapped_column(String(20)); content: Mapped[str]=mapped_column(Text); citations: Mapped[dict|None]=mapped_column(JSON)
class ArtifactChunk(UUIDMixin, TimestampMixin, Base):
    __tablename__="artifact_chunks"; __table_args__=(Index("ix_chunk_scope", "workspace_id","artifact_version_id"),)
    workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); artifact_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifacts.id")); artifact_version_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("artifact_versions.id")); scope: Mapped[str]=mapped_column(String(20)); chat_id: Mapped[uuid.UUID|None]=mapped_column(Uuid,ForeignKey("research_chats.id")); content: Mapped[str]=mapped_column(Text); chunk_index: Mapped[int]=mapped_column(Integer); page_number: Mapped[int|None]=mapped_column(Integer); section_title: Mapped[str|None]=mapped_column(String(500)); embedding: Mapped[list|None]=mapped_column(Vector(256))
class ActivityEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__="activity_events"; workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); actor_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); event_type: Mapped[str]=mapped_column(String(60)); payload: Mapped[dict]=mapped_column(JSON,default=dict)
class UserWorkspaceState(UUIDMixin, TimestampMixin, Base):
    __tablename__="user_workspace_states"; __table_args__=(UniqueConstraint("user_id","workspace_id"),); user_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("users.id")); workspace_id: Mapped[uuid.UUID]=mapped_column(Uuid,ForeignKey("workspaces.id")); last_seen_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); last_seen_commit_id: Mapped[uuid.UUID|None]=mapped_column(Uuid,ForeignKey("commits.id"))
