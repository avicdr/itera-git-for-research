import asyncio

from sqlalchemy import select

from researchgit.core.auth import hash_password
from researchgit.core.db import SessionLocal, engine
from researchgit.models import (
    ActivityEvent,
    Artifact,
    ArtifactVersion,
    Base,
    Branch,
    Comment,
    CommentThread,
    DiscussionMessage,
    DiscussionThread,
    Notification,
    ResearchReview,
    ResearchReviewDecision,
    User,
    Workspace,
    WorkspaceMember,
)
from researchgit.versioning.commits import branch_state, create_commit

DEMO_WORKSPACE_NAME = "Autonomous systems evidence"
OWNER_EMAIL = "anoushka@example.test"
COLLABORATOR_EMAIL = "maya@example.test"
OWNER_PASSWORD = "researchgit-demo"
COLLABORATOR_PASSWORD = "researchgit-collab"

HYPOTHESIS_TEXT = (
    "Autonomous systems should be deployed only with continuous human oversight "
    "and explicit rollback plans."
)
LITERATURE_TEXT = (
    "Published evaluations disagree on whether autonomous systems improve outcomes "
    "outside controlled settings."
)
COUNTER_TEXT = (
    "A narrower deployment model may be acceptable for bounded, supervised tasks "
    "if monitoring and rollback are mandatory."
)

COMMENT_SELECTED_TEXT = "continuous human oversight"
COMMENT_PROMPT = "Can you tie this to one concrete failure mode?"
COMMENT_REPLY = "Added a counter-branch draft that narrows the claim to supervised deployments."

DISCUSSION_TITLE = "Boundary for the counter-hypothesis"
DISCUSSION_OPENING = "@Maya can you sanity-check the boundary conditions before we present this to the review?"
DISCUSSION_REPLY = "I tightened the branch draft and kept the core claim conservative."

REVIEW_TITLE = "Review main vs counter-hypothesis"
REVIEW_DESCRIPTION = "Decide whether the counter branch is narrow enough for a demo-ready merge."
REVIEW_COMMENT = "This version is specific enough for the demo and keeps the risk framing intact."


async def get_or_create_user(session, *, name: str, email: str, password: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user:
        user.name = name
        if user.password_hash is None:
            user.password_hash = hash_password(password)
        return user

    user = User(name=name, email=email, password_hash=hash_password(password))
    session.add(user)
    await session.flush()
    return user


async def get_or_create_workspace(session, *, name: str, description: str, created_by: object) -> Workspace:
    workspace = (await session.execute(select(Workspace).where(Workspace.name == name))).scalar_one_or_none()
    if workspace:
        workspace.description = description
        return workspace

    workspace = Workspace(name=name, description=description, created_by=created_by)
    session.add(workspace)
    await session.flush()
    return workspace


async def get_or_create_member(session, *, workspace_id, user_id, role: str) -> WorkspaceMember:
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member:
        member.role = role
        return member

    member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
    session.add(member)
    await session.flush()
    return member


async def get_or_create_branch(session, *, workspace_id, name: str, created_by, source_branch: Branch | None = None, is_protected: bool = False) -> Branch:
    branch = (
        await session.execute(
            select(Branch).where(Branch.workspace_id == workspace_id, Branch.name == name)
    )
    ).scalar_one_or_none()
    if branch:
        branch.is_protected = is_protected
        if branch.head_commit_id is None and source_branch:
            branch.head_commit_id = source_branch.head_commit_id
        return branch

    branch = Branch(
        workspace_id=workspace_id,
        name=name,
        head_commit_id=source_branch.head_commit_id if source_branch else None,
        created_by=created_by,
        is_protected=is_protected,
    )
    session.add(branch)
    await session.flush()
    return branch


async def get_or_create_artifact(
    session,
    *,
    workspace_id,
    created_by,
    name: str,
    original_filename: str,
    text: str,
):
    artifact = (
        await session.execute(
            select(Artifact).where(
                Artifact.workspace_id == workspace_id,
                Artifact.original_filename == original_filename,
            )
    )
    ).scalar_one_or_none()
    if artifact:
        if await latest_version(session, artifact.id) is None:
            version = ArtifactVersion(
                artifact_id=artifact.id,
                version_number=1,
                storage_path="",
                content_hash="seed",
                canonical_text=text,
                created_by=created_by,
            )
            session.add(version)
            await session.flush()
        return artifact

    artifact = Artifact(
        workspace_id=workspace_id,
        name=name,
        original_filename=original_filename,
        artifact_type="DOCUMENT",
        mime_type="text/markdown",
        created_by=created_by,
        status="READY",
    )
    session.add(artifact)
    await session.flush()

    version = ArtifactVersion(
        artifact_id=artifact.id,
        version_number=1,
        storage_path="",
        content_hash="seed",
        canonical_text=text,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return artifact


async def latest_version(session, artifact_id):
    return (
        await session.execute(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact_id)
            .order_by(ArtifactVersion.version_number.desc())
        )
    ).scalars().first()


async def ensure_activity(session, *, workspace_id, actor_id, event_type: str, payload: dict) -> None:
    existing = (
        await session.execute(
            select(ActivityEvent).where(
                ActivityEvent.workspace_id == workspace_id,
                ActivityEvent.event_type == event_type,
            )
        )
    ).scalars().all()
    for event in existing:
        if event.payload == payload:
            return

    session.add(ActivityEvent(workspace_id=workspace_id, actor_id=actor_id, event_type=event_type, payload=payload))


async def ensure_notification(
    session,
    *,
    user_id,
    workspace_id,
    note_type: str,
    actor_id,
    entity_type: str,
    entity_id,
    metadata: dict,
) -> None:
    existing = (
        await session.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.workspace_id == workspace_id,
                Notification.type == note_type,
                Notification.entity_type == entity_type,
                Notification.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return

    session.add(
        Notification(
            user_id=user_id,
            workspace_id=workspace_id,
            type=note_type,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=metadata,
        )
    )


async def seed():
    async with engine.begin() as connection:
        await connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await connection.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        owner = await get_or_create_user(
            session,
            name="Anoushka",
            email=OWNER_EMAIL,
            password=OWNER_PASSWORD,
        )
        collaborator = await get_or_create_user(
            session,
            name="Maya",
            email=COLLABORATOR_EMAIL,
            password=COLLABORATOR_PASSWORD,
        )

        workspace = await get_or_create_workspace(
            session,
            name=DEMO_WORKSPACE_NAME,
            description="Demo research corpus for a two-person collaboration flow",
            created_by=owner.id,
        )

        await get_or_create_member(session, workspace_id=workspace.id, user_id=owner.id, role="OWNER")
        await get_or_create_member(session, workspace_id=workspace.id, user_id=collaborator.id, role="EDITOR")

        main = await get_or_create_branch(
            session,
            workspace_id=workspace.id,
            name="main",
            created_by=owner.id,
            is_protected=True,
        )

        hypothesis = await get_or_create_artifact(
            session,
            workspace_id=workspace.id,
            created_by=owner.id,
            name="hypothesis",
            original_filename="hypothesis.md",
            text=HYPOTHESIS_TEXT,
        )
        literature = await get_or_create_artifact(
            session,
            workspace_id=workspace.id,
            created_by=owner.id,
            name="literature-review",
            original_filename="literature-review.md",
            text=LITERATURE_TEXT,
        )

        if main.head_commit_id is None:
            state = {}
            for artifact in (hypothesis, literature):
                version = await latest_version(session, artifact.id)
                state[artifact.id] = version.id
            commit = await create_commit(
                session,
                workspace.id,
                main,
                owner.id,
                "Initial research corpus",
                state,
            )
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=owner.id,
                event_type="commit_created",
                payload={"commit_id": str(commit.id)},
            )

        counter = await get_or_create_branch(
            session,
            workspace_id=workspace.id,
            name="counter-hypothesis",
            created_by=owner.id,
            source_branch=main,
            is_protected=False,
        )

        if counter.head_commit_id == main.head_commit_id:
            counter_version = ArtifactVersion(
                artifact_id=hypothesis.id,
                version_number=(await latest_version(session, hypothesis.id)).version_number + 1,
                storage_path="",
                content_hash="seed-counter",
                canonical_text=COUNTER_TEXT,
                created_by=collaborator.id,
            )
            session.add(counter_version)
            await session.flush()

            state = await branch_state(session, main.head_commit_id)
            state[hypothesis.id] = counter_version.id
            commit = await create_commit(
                session,
                workspace.id,
                counter,
                collaborator.id,
                "Tighten the counter-hypothesis",
                state,
            )
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=collaborator.id,
                event_type="commit_created",
                payload={"commit_id": str(commit.id)},
            )
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=collaborator.id,
                event_type="branch_updated",
                payload={"branch": "counter-hypothesis"},
            )

        main_version = await latest_version(session, hypothesis.id)
        comment_thread = (
            await session.execute(
                select(CommentThread).where(
                    CommentThread.workspace_id == workspace.id,
                    CommentThread.artifact_id == hypothesis.id,
                    CommentThread.selected_text == COMMENT_SELECTED_TEXT,
                )
            )
        ).scalar_one_or_none()
        if not comment_thread:
            comment_thread = CommentThread(
                workspace_id=workspace.id,
                artifact_id=hypothesis.id,
                artifact_version_id=main_version.id,
                anchor={"from": 0, "to": len(COMMENT_SELECTED_TEXT)},
                selected_text=COMMENT_SELECTED_TEXT,
                created_by=owner.id,
            )
            session.add(comment_thread)
            await session.flush()
            session.add(
                Comment(
                    thread_id=comment_thread.id,
                    user_id=owner.id,
                    content=COMMENT_PROMPT,
                )
            )
            session.add(
                Comment(
                    thread_id=comment_thread.id,
                    user_id=collaborator.id,
                    content=COMMENT_REPLY,
                )
            )
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=owner.id,
                event_type="comment_created",
                payload={"artifact_id": str(hypothesis.id), "thread_id": str(comment_thread.id)},
            )

        discussion = (
            await session.execute(
                select(DiscussionThread).where(
                    DiscussionThread.workspace_id == workspace.id,
                    DiscussionThread.title == DISCUSSION_TITLE,
                )
            )
        ).scalar_one_or_none()
        if not discussion:
            discussion = DiscussionThread(
                workspace_id=workspace.id,
                scope="WORKSPACE",
                title=DISCUSSION_TITLE,
                created_by=owner.id,
            )
            session.add(discussion)
            await session.flush()
            session.add(
                DiscussionMessage(
                    thread_id=discussion.id,
                    user_id=owner.id,
                    content=DISCUSSION_OPENING,
                    references={},
                )
            )
            session.add(
                DiscussionMessage(
                    thread_id=discussion.id,
                    user_id=collaborator.id,
                    content=DISCUSSION_REPLY,
                    references={},
                )
            )
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=owner.id,
                event_type="discussion_created",
                payload={"thread_id": str(discussion.id)},
            )
            await ensure_notification(
                session,
                user_id=collaborator.id,
                workspace_id=workspace.id,
                note_type="MENTION",
                actor_id=owner.id,
                entity_type="DISCUSSION",
                entity_id=discussion.id,
                metadata={"content": DISCUSSION_OPENING[:240]},
            )

        review = (
            await session.execute(
                select(ResearchReview).where(
                    ResearchReview.workspace_id == workspace.id,
                    ResearchReview.title == REVIEW_TITLE,
                )
            )
        ).scalar_one_or_none()
        if not review:
            review = ResearchReview(
                workspace_id=workspace.id,
                source_branch_id=counter.id,
                target_branch_id=main.id,
                title=REVIEW_TITLE,
                description=REVIEW_DESCRIPTION,
                created_by=owner.id,
                status="OPEN",
            )
            session.add(review)
            await session.flush()
            session.add(
                ResearchReviewDecision(
                    review_id=review.id,
                    reviewer_id=collaborator.id,
                    decision="APPROVED",
                    comment=REVIEW_COMMENT,
                )
            )
            review.status = "APPROVED"
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=owner.id,
                event_type="review_requested",
                payload={"review_id": str(review.id)},
            )
            await ensure_activity(
                session,
                workspace_id=workspace.id,
                actor_id=collaborator.id,
                event_type="review_decided",
                payload={"review_id": str(review.id), "decision": "APPROVED"},
            )
            await ensure_notification(
                session,
                user_id=collaborator.id,
                workspace_id=workspace.id,
                note_type="REVIEW_REQUESTED",
                actor_id=owner.id,
                entity_type="REVIEW",
                entity_id=review.id,
                metadata={"title": REVIEW_TITLE},
            )

        await session.commit()
        print(workspace.id)


def main():
    asyncio.run(seed())


if __name__ == "__main__":
    main()
