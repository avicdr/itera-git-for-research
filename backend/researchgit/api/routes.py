import hashlib, json, re, uuid, secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, Response, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from researchgit.core.db import get_session
from researchgit.core.config import settings
from researchgit.models import *
from researchgit.ingestion.processing import process
from researchgit.versioning.commits import branch_state, create_commit
from researchgit.versioning.diff import structural_diff
from researchgit.versioning.merge import plan_merge
from researchgit.rag.query_service import answer
from researchgit.core.auth import SESSION_COOKIE, active_user, create_session, current_user, hash_password, require_workspace_member, require_workspace_role, token_hash, utcnow, verify_password

auth_router=APIRouter(prefix="/api/auth", tags=["authentication"])
public_router=APIRouter(prefix="/api")
router=APIRouter(prefix="/api", dependencies=[Depends(current_user)])
def err(code,msg,status=400): raise HTTPException(status,detail={"error":{"code":code,"message":msg}})
async def user(session):
    u=active_user.get()
    if not u: err("AUTH_REQUIRED","Sign in to continue.",401)
    return u
async def workspace_or_404(session,id):
    w=await session.get(Workspace,id)
    if not w: err("WORKSPACE_NOT_FOUND","Workspace not found",404)
    u=active_user.get()
    if u: await require_workspace_member(session,w.id,u.id)
    return w
class WorkspaceIn(BaseModel): name:str; description:str|None=None
class BranchIn(BaseModel): name:str; source_branch_id:uuid.UUID|None=None
class CommitIn(BaseModel): message:str; artifact_version_ids:dict[uuid.UUID,uuid.UUID]|None=None
class DocIn(BaseModel): text:str; editor_json:dict|None=None
class MergeIn(BaseModel): source_branch_id:uuid.UUID; target_branch_id:uuid.UUID
class ResolveIn(BaseModel): resolution:str; text:str|None=None
class ChatIn(BaseModel): title:str; branch_id:uuid.UUID|None=None
class QueryIn(BaseModel): message:str; branch_id:uuid.UUID; context:dict=Field(default_factory=dict); commit_id:uuid.UUID|None=None
class RegisterIn(BaseModel): name:str=Field(min_length=1,max_length=120); email:str; password:str
class LoginIn(BaseModel): email:str; password:str
class InviteIn(BaseModel): role:str="EDITOR"; expires_in_days:int=7; max_uses:int|None=None
class MemberRoleIn(BaseModel): role:str
class CommentThreadIn(BaseModel): selected_text:str=Field(min_length=1); anchor:dict=Field(default_factory=dict); artifact_version_id:uuid.UUID|None=None; content:str=Field(min_length=1)
class CommentIn(BaseModel): content:str=Field(min_length=1)
class PdfAnnotationIn(BaseModel): page_number:int=Field(ge=1); selected_text:str=""; anchor_data:dict=Field(default_factory=dict); note:str|None=None; artifact_version_id:uuid.UUID|None=None
class DiscussionIn(BaseModel): scope:str="WORKSPACE"; title:str|None=None; branch_id:uuid.UUID|None=None; artifact_id:uuid.UUID|None=None; content:str=Field(min_length=1); references:dict=Field(default_factory=dict)
class DiscussionMessageIn(BaseModel): content:str=Field(min_length=1); references:dict=Field(default_factory=dict)
class ReviewIn(BaseModel): source_branch_id:uuid.UUID; target_branch_id:uuid.UUID; title:str=Field(min_length=1,max_length=300); description:str|None=None
class ReviewDecisionIn(BaseModel): decision:str; comment:str|None=None

def public_user(u: User): return {"id":str(u.id),"name":u.name,"email":u.email,"avatar_url":u.avatar_url}
def session_response(payload: dict, token: str):
    response=JSONResponse(payload)
    response.set_cookie(SESSION_COOKIE,token,httponly=True,samesite="lax",secure=settings.session_cookie_secure,max_age=settings.session_days*86400,path="/")
    return response
async def notify_mentions(session,workspace_id,actor_id,content,entity_type,entity_id):
    names=re.findall(r"@([\w .'-]+?)(?=[,!.?\n]|$)",content)
    if not names:return
    rows=(await session.execute(select(WorkspaceMember,User).join(User,User.id==WorkspaceMember.user_id).where(WorkspaceMember.workspace_id==workspace_id))).all()
    for _,person in rows:
        if person.id!=actor_id and any(person.name.lower()==name.strip().lower() for name in names): session.add(Notification(user_id=person.id,workspace_id=workspace_id,type="MENTION",actor_id=actor_id,entity_type=entity_type,entity_id=entity_id,metadata_json={"content":content[:240]}))

@auth_router.post("/register", status_code=201)
async def register(data:RegisterIn, session:AsyncSession=Depends(get_session)):
    email=data.email.strip().lower()
    if (await session.execute(select(User).where(User.email==email))).scalar_one_or_none(): err("EMAIL_IN_USE","An account already uses this email.",409)
    try: password_hash=hash_password(data.password)
    except ValueError as exc: err("WEAK_PASSWORD",str(exc),422)
    u=User(name=data.name.strip(),email=email,password_hash=password_hash); session.add(u); await session.flush(); token,_=await create_session(session,u.id); await session.commit(); return session_response({"user":public_user(u)},token)

@auth_router.post("/login")
async def login(data:LoginIn, session:AsyncSession=Depends(get_session)):
    u=(await session.execute(select(User).where(User.email==data.email.strip().lower()))).scalar_one_or_none()
    if not u or not verify_password(data.password,u.password_hash): err("INVALID_CREDENTIALS","Email or password is incorrect.",401)
    token,_=await create_session(session,u.id); await session.commit(); return session_response({"user":public_user(u)},token)

@auth_router.post("/logout", status_code=204)
async def logout(request:Request, session:AsyncSession=Depends(get_session), u:User=Depends(current_user)):
    token=request.cookies.get(SESSION_COOKIE)
    if token:
        record=(await session.execute(select(UserSession).where(UserSession.user_id==u.id,UserSession.token_hash==token_hash(token),UserSession.revoked_at.is_(None)))).scalar_one_or_none()
        if record: record.revoked_at=utcnow(); await session.commit()
    response=Response(status_code=204); response.delete_cookie(SESSION_COOKIE,path="/"); return response

@auth_router.get("/me")
async def me(u:User=Depends(current_user)): return {"user":public_user(u)}

@router.get("/workspaces/{workspace_id}/members")
async def members(workspace_id:uuid.UUID, session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session, workspace_id)
    rows=(await session.execute(select(WorkspaceMember, User).join(User, User.id==WorkspaceMember.user_id).where(WorkspaceMember.workspace_id==workspace_id).order_by(WorkspaceMember.created_at))).all()
    return [{**public_user(member_user), "role":member.role, "joined_at":member.created_at} for member,member_user in rows]

@router.patch("/workspaces/{workspace_id}/members/{member_id}")
async def change_member_role(workspace_id:uuid.UUID, member_id:uuid.UUID, data:MemberRoleIn, session:AsyncSession=Depends(get_session)):
    u=await user(session); await require_workspace_role(session,workspace_id,u.id,"OWNER")
    role=data.role.upper()
    if role not in {"OWNER","EDITOR","VIEWER"}: err("INVALID_ROLE","Role must be OWNER, EDITOR, or VIEWER.",422)
    member=await session.get(WorkspaceMember,member_id)
    if not member or member.workspace_id!=workspace_id: err("MEMBER_NOT_FOUND","Member not found.",404)
    member.role=role; await session.commit(); return {"id":str(member.id),"role":member.role}

@router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=204)
async def remove_member(workspace_id:uuid.UUID, member_id:uuid.UUID, session:AsyncSession=Depends(get_session)):
    u=await user(session); await require_workspace_role(session,workspace_id,u.id,"OWNER")
    member=await session.get(WorkspaceMember,member_id)
    if not member or member.workspace_id!=workspace_id: err("MEMBER_NOT_FOUND","Member not found.",404)
    if member.user_id==u.id: err("OWNER_REMOVAL_FORBIDDEN","Transfer ownership before removing yourself.",422)
    await session.delete(member); await session.commit()

@router.post("/workspaces/{workspace_id}/invites", status_code=201)
async def create_invite(workspace_id:uuid.UUID, data:InviteIn, session:AsyncSession=Depends(get_session)):
    u=await user(session); await require_workspace_role(session,workspace_id,u.id,"EDITOR")
    role=data.role.upper()
    if role not in {"EDITOR","VIEWER"}: err("INVALID_INVITE_ROLE","Invite role must be EDITOR or VIEWER.",422)
    if not 1 <= data.expires_in_days <= 30: err("INVALID_EXPIRY","Invite expiry must be between 1 and 30 days.",422)
    if data.max_uses is not None and data.max_uses < 1: err("INVALID_MAX_USES","Maximum uses must be at least one.",422)
    token=secrets.token_urlsafe(32)
    invite=WorkspaceInvite(workspace_id=workspace_id,created_by=u.id,token_hash=token_hash(token),role=role,expires_at=utcnow()+timedelta(days=data.expires_in_days),max_uses=data.max_uses)
    session.add(invite); await session.commit()
    return {"id":str(invite.id),"token":token,"invite_path":f"/invite/{token}","role":invite.role,"expires_at":invite.expires_at,"max_uses":invite.max_uses}

@public_router.get("/invites/{token}")
async def invite_detail(token:str, session:AsyncSession=Depends(get_session)):
    invite=(await session.execute(select(WorkspaceInvite).where(WorkspaceInvite.token_hash==token_hash(token)))).scalar_one_or_none()
    if not invite or invite.revoked_at or invite.expires_at <= utcnow() or (invite.max_uses is not None and invite.use_count >= invite.max_uses): err("INVITE_UNAVAILABLE","This invite link has expired, been revoked, or reached its use limit.",404)
    workspace=await session.get(Workspace,invite.workspace_id)
    return {"workspace_id":str(invite.workspace_id),"workspace_name":workspace.name if workspace else "Research workspace","role":invite.role,"expires_at":invite.expires_at}

@router.post("/invites/{token}/accept")
async def accept_invite(token:str, session:AsyncSession=Depends(get_session)):
    u=await user(session); invite=(await session.execute(select(WorkspaceInvite).where(WorkspaceInvite.token_hash==token_hash(token)))).scalar_one_or_none()
    if not invite or invite.revoked_at or invite.expires_at <= utcnow() or (invite.max_uses is not None and invite.use_count >= invite.max_uses): err("INVITE_UNAVAILABLE","This invite link has expired, been revoked, or reached its use limit.",404)
    existing=(await session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id==invite.workspace_id,WorkspaceMember.user_id==u.id))).scalar_one_or_none()
    if not existing:
        session.add(WorkspaceMember(workspace_id=invite.workspace_id,user_id=u.id,role=invite.role)); invite.use_count+=1
    await session.commit(); return {"workspace_id":str(invite.workspace_id),"role":existing.role if existing else invite.role,"already_member":bool(existing)}

@router.post("/workspaces/{workspace_id}/invites/{invite_id}/revoke", status_code=204)
async def revoke_invite(workspace_id:uuid.UUID,invite_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    u=await user(session); await require_workspace_role(session,workspace_id,u.id,"EDITOR"); invite=await session.get(WorkspaceInvite,invite_id)
    if not invite or invite.workspace_id!=workspace_id: err("INVITE_NOT_FOUND","Invite not found.",404)
    invite.revoked_at=utcnow(); await session.commit()

def serialize_comment(comment:Comment, author:User): return {"id":str(comment.id),"content":comment.content,"created_at":comment.created_at,"updated_at":comment.updated_at,"author":public_user(author)}

@router.get("/artifacts/{artifact_id}/comments")
async def list_comments(artifact_id:uuid.UUID, include_resolved:bool=False, session:AsyncSession=Depends(get_session)):
    artifact=await session.get(Artifact,artifact_id)
    if not artifact: err("ARTIFACT_NOT_FOUND","Artifact not found.",404)
    u=await user(session); await require_workspace_member(session,artifact.workspace_id,u.id)
    statement=select(CommentThread).where(CommentThread.artifact_id==artifact_id)
    if not include_resolved: statement=statement.where(CommentThread.resolved_at.is_(None))
    threads=(await session.execute(statement.order_by(desc(CommentThread.created_at)))).scalars().all(); result=[]
    for thread in threads:
        rows=(await session.execute(select(Comment,User).join(User,User.id==Comment.user_id).where(Comment.thread_id==thread.id).order_by(Comment.created_at))).all()
        result.append({"id":str(thread.id),"selected_text":thread.selected_text,"anchor":thread.anchor,"artifact_version_id":str(thread.artifact_version_id) if thread.artifact_version_id else None,"created_at":thread.created_at,"resolved_at":thread.resolved_at,"comments":[serialize_comment(comment,author) for comment,author in rows]})
    return result

@router.post("/artifacts/{artifact_id}/comments",status_code=201)
async def create_comment_thread(artifact_id:uuid.UUID,data:CommentThreadIn,session:AsyncSession=Depends(get_session)):
    artifact=await session.get(Artifact,artifact_id)
    if not artifact or artifact.artifact_type!="DOCUMENT": err("INVALID_ARTIFACT","Comments can only be added to research documents.",404)
    u=await user(session); await require_workspace_member(session,artifact.workspace_id,u.id)
    thread=CommentThread(workspace_id=artifact.workspace_id,artifact_id=artifact.id,artifact_version_id=data.artifact_version_id,anchor=data.anchor,selected_text=data.selected_text,created_by=u.id);session.add(thread);await session.flush();comment=Comment(thread_id=thread.id,user_id=u.id,content=data.content);session.add(comment);session.add(ActivityEvent(workspace_id=artifact.workspace_id,actor_id=u.id,event_type="comment_created",payload={"artifact_id":str(artifact.id),"thread_id":str(thread.id)}));await session.commit();return {"id":str(thread.id),"comments":[serialize_comment(comment,u)]}

@router.post("/comment-threads/{thread_id}/comments",status_code=201)
async def reply_comment(thread_id:uuid.UUID,data:CommentIn,session:AsyncSession=Depends(get_session)):
    thread=await session.get(CommentThread,thread_id)
    if not thread: err("COMMENT_THREAD_NOT_FOUND","Comment thread not found.",404)
    u=await user(session);await require_workspace_member(session,thread.workspace_id,u.id);comment=Comment(thread_id=thread.id,user_id=u.id,content=data.content);session.add(comment);await session.commit();return serialize_comment(comment,u)

@router.post("/comment-threads/{thread_id}/resolve")
async def resolve_comment(thread_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    thread=await session.get(CommentThread,thread_id)
    if not thread: err("COMMENT_THREAD_NOT_FOUND","Comment thread not found.",404)
    u=await user(session);await require_workspace_role(session,thread.workspace_id,u.id,"EDITOR");thread.resolved_at=datetime.utcnow();session.add(ActivityEvent(workspace_id=thread.workspace_id,actor_id=u.id,event_type="comment_resolved",payload={"thread_id":str(thread.id)}));await session.commit();return {"id":str(thread.id),"resolved_at":thread.resolved_at}

@router.get("/artifacts/{artifact_id}/annotations")
async def list_pdf_annotations(artifact_id:uuid.UUID,page:int|None=None,session:AsyncSession=Depends(get_session)):
    artifact=await session.get(Artifact,artifact_id)
    if not artifact or artifact.artifact_type!="PDF":err("INVALID_ARTIFACT","PDF annotation target not found.",404)
    u=await user(session);await require_workspace_member(session,artifact.workspace_id,u.id); statement=select(PdfAnnotation,User).join(User,User.id==PdfAnnotation.created_by).where(PdfAnnotation.artifact_id==artifact_id)
    if page: statement=statement.where(PdfAnnotation.page_number==page)
    rows=(await session.execute(statement.order_by(desc(PdfAnnotation.created_at)))).all();return [{"id":str(annotation.id),"page_number":annotation.page_number,"selected_text":annotation.selected_text,"anchor_data":annotation.anchor_data,"note":annotation.note,"created_at":annotation.created_at,"resolved_at":annotation.resolved_at,"author":public_user(author)} for annotation,author in rows]

@router.post("/artifacts/{artifact_id}/annotations",status_code=201)
async def create_pdf_annotation(artifact_id:uuid.UUID,data:PdfAnnotationIn,session:AsyncSession=Depends(get_session)):
    artifact=await session.get(Artifact,artifact_id)
    if not artifact or artifact.artifact_type!="PDF":err("INVALID_ARTIFACT","PDF annotation target not found.",404)
    u=await user(session);await require_workspace_member(session,artifact.workspace_id,u.id)
    version_id=data.artifact_version_id
    if not version_id: version_id=(await session.execute(select(ArtifactVersion.id).where(ArtifactVersion.artifact_id==artifact.id).order_by(desc(ArtifactVersion.version_number)))).scalar_one()
    annotation=PdfAnnotation(workspace_id=artifact.workspace_id,artifact_id=artifact.id,artifact_version_id=version_id,page_number=data.page_number,selected_text=data.selected_text,anchor_data=data.anchor_data,note=data.note,created_by=u.id);session.add(annotation);session.add(ActivityEvent(workspace_id=artifact.workspace_id,actor_id=u.id,event_type="pdf_annotation_created",payload={"artifact_id":str(artifact.id),"annotation_id":str(annotation.id),"page":data.page_number}));await session.commit();return {"id":str(annotation.id),"page_number":annotation.page_number,"note":annotation.note}

@router.get("/workspaces/{workspace_id}/discussions")
async def list_discussions(workspace_id:uuid.UUID,scope:str|None=None,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); statement=select(DiscussionThread).where(DiscussionThread.workspace_id==workspace_id)
    if scope:statement=statement.where(DiscussionThread.scope==scope.upper())
    threads=(await session.execute(statement.order_by(desc(DiscussionThread.updated_at)))).scalars().all();return [{"id":str(thread.id),"scope":thread.scope,"title":thread.title,"branch_id":str(thread.branch_id) if thread.branch_id else None,"artifact_id":str(thread.artifact_id) if thread.artifact_id else None,"created_at":thread.created_at} for thread in threads]

@router.post("/workspaces/{workspace_id}/discussions",status_code=201)
async def create_discussion(workspace_id:uuid.UUID,data:DiscussionIn,session:AsyncSession=Depends(get_session)):
    u=await user(session);await require_workspace_member(session,workspace_id,u.id);scope=data.scope.upper()
    if scope not in {"WORKSPACE","BRANCH","ARTIFACT"}:err("INVALID_DISCUSSION_SCOPE","Scope must be WORKSPACE, BRANCH, or ARTIFACT.",422)
    if scope=="BRANCH" and not data.branch_id:err("BRANCH_REQUIRED","A branch discussion needs a research direction.",422)
    if scope=="ARTIFACT" and not data.artifact_id:err("ARTIFACT_REQUIRED","An artifact discussion needs a source.",422)
    thread=DiscussionThread(workspace_id=workspace_id,scope=scope,title=data.title,branch_id=data.branch_id,artifact_id=data.artifact_id,created_by=u.id);session.add(thread);await session.flush();message=DiscussionMessage(thread_id=thread.id,user_id=u.id,content=data.content,references=data.references);session.add(message);await notify_mentions(session,workspace_id,u.id,data.content,"DISCUSSION",thread.id);session.add(ActivityEvent(workspace_id=workspace_id,actor_id=u.id,event_type="discussion_created",payload={"thread_id":str(thread.id)}));await session.commit();return {"id":str(thread.id)}

@router.get("/discussions/{thread_id}")
async def discussion_detail(thread_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    thread=await session.get(DiscussionThread,thread_id)
    if not thread:err("DISCUSSION_NOT_FOUND","Discussion not found.",404)
    u=await user(session);await require_workspace_member(session,thread.workspace_id,u.id);rows=(await session.execute(select(DiscussionMessage,User).join(User,User.id==DiscussionMessage.user_id).where(DiscussionMessage.thread_id==thread_id).order_by(DiscussionMessage.created_at))).all();return {"id":str(thread.id),"title":thread.title,"scope":thread.scope,"messages":[{"id":str(message.id),"content":message.content,"references":message.references,"created_at":message.created_at,"author":public_user(author)} for message,author in rows]}

@router.post("/discussions/{thread_id}/messages",status_code=201)
async def reply_discussion(thread_id:uuid.UUID,data:DiscussionMessageIn,session:AsyncSession=Depends(get_session)):
    thread=await session.get(DiscussionThread,thread_id)
    if not thread:err("DISCUSSION_NOT_FOUND","Discussion not found.",404)
    u=await user(session);await require_workspace_member(session,thread.workspace_id,u.id);message=DiscussionMessage(thread_id=thread.id,user_id=u.id,content=data.content,references=data.references);session.add(message);await session.flush();await notify_mentions(session,thread.workspace_id,u.id,data.content,"DISCUSSION",thread.id);await session.commit();return {"id":str(message.id)}

@router.get("/notifications")
async def notifications(unread_only:bool=False,session:AsyncSession=Depends(get_session)):
    u=await user(session);statement=select(Notification,User).outerjoin(User,User.id==Notification.actor_id).where(Notification.user_id==u.id)
    if unread_only:statement=statement.where(Notification.read_at.is_(None))
    rows=(await session.execute(statement.order_by(desc(Notification.created_at)).limit(100))).all();return [{"id":str(note.id),"type":note.type,"workspace_id":str(note.workspace_id),"entity_type":note.entity_type,"entity_id":str(note.entity_id) if note.entity_id else None,"read_at":note.read_at,"created_at":note.created_at,"actor":public_user(actor) if actor else None,"metadata":note.metadata_json} for note,actor in rows]

@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    u=await user(session);note=await session.get(Notification,notification_id)
    if not note or note.user_id!=u.id:err("NOTIFICATION_NOT_FOUND","Notification not found.",404)
    note.read_at=datetime.utcnow();await session.commit();return {"id":str(note.id),"read_at":note.read_at}

@router.get("/workspaces/{workspace_id}/reviews")
async def list_reviews(workspace_id:uuid.UUID,status:str|None=None,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id);statement=select(ResearchReview).where(ResearchReview.workspace_id==workspace_id)
    if status:statement=statement.where(ResearchReview.status==status.upper())
    rows=(await session.execute(statement.order_by(desc(ResearchReview.updated_at)))).scalars().all();return [{"id":str(review.id),"title":review.title,"description":review.description,"source_branch_id":str(review.source_branch_id),"target_branch_id":str(review.target_branch_id),"status":review.status,"created_at":review.created_at,"merged_at":review.merged_at} for review in rows]

@router.post("/workspaces/{workspace_id}/reviews",status_code=201)
async def create_review(workspace_id:uuid.UUID,data:ReviewIn,session:AsyncSession=Depends(get_session)):
    u=await user(session);await require_workspace_role(session,workspace_id,u.id,"EDITOR");source=await session.get(Branch,data.source_branch_id);target=await session.get(Branch,data.target_branch_id)
    if not source or not target or source.workspace_id!=workspace_id or target.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Both research directions must be in this workspace.",404)
    if source.id==target.id:err("INVALID_REVIEW","Choose two different research directions.",422)
    review=ResearchReview(workspace_id=workspace_id,source_branch_id=source.id,target_branch_id=target.id,title=data.title,description=data.description,created_by=u.id);session.add(review);await session.flush();members=(await session.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id==workspace_id,WorkspaceMember.user_id!=u.id))).scalars().all()
    for member in members:session.add(Notification(user_id=member.user_id,workspace_id=workspace_id,type="REVIEW_REQUESTED",actor_id=u.id,entity_type="REVIEW",entity_id=review.id,metadata_json={"title":review.title}))
    session.add(ActivityEvent(workspace_id=workspace_id,actor_id=u.id,event_type="review_created",payload={"review_id":str(review.id)}));await session.commit();return {"id":str(review.id),"status":review.status}

@router.get("/reviews/{review_id}")
async def review_detail(review_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    review=await session.get(ResearchReview,review_id)
    if not review:err("REVIEW_NOT_FOUND","Research review not found.",404)
    u=await user(session);await require_workspace_member(session,review.workspace_id,u.id);source=await session.get(Branch,review.source_branch_id);target=await session.get(Branch,review.target_branch_id);decisions=(await session.execute(select(ResearchReviewDecision,User).join(User,User.id==ResearchReviewDecision.reviewer_id).where(ResearchReviewDecision.review_id==review.id))).all();return {"id":str(review.id),"title":review.title,"description":review.description,"status":review.status,"source":{"id":str(source.id),"name":source.name},"target":{"id":str(target.id),"name":target.name},"decisions":[{"decision":decision.decision,"comment":decision.comment,"reviewer":public_user(reviewer)} for decision,reviewer in decisions]}

@router.post("/reviews/{review_id}/decision")
async def decide_review(review_id:uuid.UUID,data:ReviewDecisionIn,session:AsyncSession=Depends(get_session)):
    review=await session.get(ResearchReview,review_id)
    if not review:err("REVIEW_NOT_FOUND","Research review not found.",404)
    u=await user(session);await require_workspace_member(session,review.workspace_id,u.id);decision=data.decision.upper()
    if decision not in {"APPROVED","CHANGES_REQUESTED"}:err("INVALID_REVIEW_DECISION","Decision must be APPROVED or CHANGES_REQUESTED.",422)
    existing=(await session.execute(select(ResearchReviewDecision).where(ResearchReviewDecision.review_id==review.id,ResearchReviewDecision.reviewer_id==u.id))).scalar_one_or_none()
    if existing:existing.decision=decision;existing.comment=data.comment
    else:session.add(ResearchReviewDecision(review_id=review.id,reviewer_id=u.id,decision=decision,comment=data.comment))
    review.status=decision;await session.commit();return {"id":str(review.id),"status":review.status}

@router.post("/workspaces")
async def create_workspace(data:WorkspaceIn, session:AsyncSession=Depends(get_session)):
    u=await user(session); w=Workspace(**data.model_dump(),created_by=u.id); session.add(w); await session.flush(); session.add(WorkspaceMember(workspace_id=w.id,user_id=u.id,role="OWNER")); session.add(Branch(workspace_id=w.id,name="main",created_by=u.id,is_protected=True)); await session.commit(); return {"id":w.id,"name":w.name,"description":w.description}
@router.get("/workspaces")
async def list_workspaces(session:AsyncSession=Depends(get_session)):
    u=await user(session); rows=(await session.execute(select(Workspace).join(WorkspaceMember).where(Workspace.archived==False,WorkspaceMember.user_id==u.id).order_by(desc(Workspace.updated_at)))).scalars(); return [{"id":x.id,"name":x.name,"description":x.description,"updated_at":x.updated_at} for x in rows]
@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    w=await workspace_or_404(session,workspace_id); branches=(await session.execute(select(Branch).where(Branch.workspace_id==w.id))).scalars().all(); return {"id":w.id,"name":w.name,"description":w.description,"branches":[{"id":b.id,"name":b.name,"head_commit_id":b.head_commit_id} for b in branches]}
@router.patch("/workspaces/{workspace_id}")
async def patch_workspace(workspace_id:uuid.UUID,data:WorkspaceIn,session:AsyncSession=Depends(get_session)):
    w=await workspace_or_404(session,workspace_id); u=await user(session); await require_workspace_role(session,workspace_id,u.id,"OWNER"); w.name=data.name;w.description=data.description;await session.commit();return {"id":w.id,"name":w.name}
@router.post("/workspaces/{workspace_id}/artifacts")
async def upload(workspace_id:uuid.UUID,file:UploadFile=File(...),scope:str=Form("WORKSPACE"),chat_id:uuid.UUID|None=Form(None),session:AsyncSession=Depends(get_session)):
    w=await workspace_or_404(session,workspace_id); u=await user(session); await require_workspace_role(session,workspace_id,u.id,"EDITOR"); suffix=Path(file.filename or "").suffix.lower(); allowed={".md":"DOCUMENT",".txt":"DOCUMENT",".pdf":"PDF",".json":"CHAT_EXPORT"}
    if suffix not in allowed: err("UNSUPPORTED_FILE","Supported: .md, .txt, .pdf, .json",415)
    content=await file.read()
    if len(content)>settings.max_upload_bytes: err("FILE_TOO_LARGE","Upload exceeds configured limit",413)
    safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(file.filename or "artifact").name); a=Artifact(workspace_id=w.id,name=Path(safe).stem,original_filename=safe,artifact_type=allowed[suffix],mime_type=file.content_type or ("application/pdf" if suffix==".pdf" else "text/plain"),scope=scope,chat_id=chat_id,created_by=u.id,status="PROCESSING");session.add(a);await session.flush()
    rel=Path("workspaces")/str(w.id)/"artifacts"/str(a.id)/"versions"/"v1"/safe; target=settings.storage_root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content);v=ArtifactVersion(artifact_id=a.id,version_number=1,storage_path=str(rel),content_hash=hashlib.sha256(content).hexdigest(),created_by=u.id);session.add(v);await session.flush(); await process(session,a,v,settings.storage_root);session.add(ActivityEvent(workspace_id=w.id,actor_id=u.id,event_type="file_imported",payload={"artifact_id":str(a.id)}));await session.commit();return {"id":a.id,"status":a.status,"version_id":v.id}
@router.get("/workspaces/{workspace_id}/artifacts")
async def artifacts(workspace_id:uuid.UUID,branch_id:uuid.UUID|None=None,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); q=select(Artifact).where(Artifact.workspace_id==workspace_id,Artifact.deleted_at==None); rows=(await session.execute(q)).scalars().all(); visible={}
    if branch_id: visible=await branch_state(session,(await session.get(Branch,branch_id)).head_commit_id)
    return [{"id":a.id,"name":a.name,"type":a.artifact_type,"status":a.status,"scope":a.scope,"version_id":visible.get(a.id)} for a in rows if not visible or a.id in visible]
@router.get("/workspaces/{workspace_id}/working-changes")
async def working_changes(workspace_id:uuid.UUID,branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); branch=await session.get(Branch,branch_id)
    if not branch or branch.workspace_id!=workspace_id: err("BRANCH_NOT_FOUND","Branch not found",404)
    head=await branch_state(session,branch.head_commit_id); results=[]
    artifacts=(await session.execute(select(Artifact).where(Artifact.workspace_id==workspace_id,Artifact.deleted_at==None))).scalars().all()
    for artifact in artifacts:
        latest=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==artifact.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first()
        previous=head.get(artifact.id)
        if previous != latest.id:
            old=await session.get(ArtifactVersion,previous) if previous else None
            results.append({"artifact_id":artifact.id,"name":artifact.name,"kind":"A" if not previous else "M","latest_version_id":latest.id,"diff":structural_diff(old.canonical_text if old else "",latest.canonical_text)})
    return {"branch_id":branch.id,"changes":results}
@router.get("/artifacts/{artifact_id}")
async def artifact(artifact_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    a=await session.get(Artifact,artifact_id)
    if not a:err("ARTIFACT_NOT_FOUND","Artifact not found",404)
    u=await user(session); await require_workspace_member(session,a.workspace_id,u.id)
    v=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==a.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first();return {"id":a.id,"workspace_id":a.workspace_id,"name":a.name,"type":a.artifact_type,"status":a.status,"version": {"id":v.id,"text":v.canonical_text,"editor_json":v.editor_json,"number":v.version_number}}
@router.post("/workspaces/{workspace_id}/documents")
async def create_document(workspace_id:uuid.UUID,data:DocIn, name:str="untitled.md",session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id);u=await user(session);await require_workspace_role(session,workspace_id,u.id,"EDITOR");safe=re.sub(r"[^A-Za-z0-9._-]","_",Path(name).name)
    if not safe.endswith((".md",".txt")): safe += ".md"
    a=Artifact(workspace_id=workspace_id,name=Path(safe).stem,original_filename=safe,artifact_type="DOCUMENT",mime_type="text/markdown",created_by=u.id,status="PROCESSING");session.add(a);await session.flush()
    rel=Path("workspaces")/str(workspace_id)/"artifacts"/str(a.id)/"versions"/"v1"/safe;p=settings.storage_root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data.text)
    v=ArtifactVersion(artifact_id=a.id,version_number=1,storage_path=str(rel),content_hash=hashlib.sha256(data.text.encode()).hexdigest(),editor_json=data.editor_json,created_by=u.id);session.add(v);await session.flush();await process(session,a,v,settings.storage_root);await session.commit();return {"id":a.id,"version_id":v.id}
@router.get("/artifacts/{artifact_id}/file")
async def artifact_file(artifact_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    a=await session.get(Artifact,artifact_id);v=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==artifact_id).order_by(desc(ArtifactVersion.version_number)))).scalars().first()
    if not a or not v:err("ARTIFACT_NOT_FOUND","Artifact not found",404)
    u=await user(session); await require_workspace_member(session,a.workspace_id,u.id)
    p=(settings.storage_root/v.storage_path).resolve()
    if settings.storage_root.resolve() not in p.parents or not p.is_file():err("FILE_NOT_FOUND","Stored file unavailable",404)
    return FileResponse(p,filename=a.original_filename,media_type=a.mime_type)
@router.put("/artifacts/{artifact_id}/document")
async def save_doc(artifact_id:uuid.UUID,data:DocIn,session:AsyncSession=Depends(get_session)):
    a=await session.get(Artifact,artifact_id)
    if not a or a.artifact_type!="DOCUMENT":err("INVALID_ARTIFACT","Editable document not found",404)
    u=await user(session); await require_workspace_role(session,a.workspace_id,u.id,"EDITOR"); last=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==a.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first();n=last.version_number+1; rel=Path("workspaces")/str(a.workspace_id)/"artifacts"/str(a.id)/"versions"/f"v{n}"/a.original_filename;p=settings.storage_root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data.text);v=ArtifactVersion(artifact_id=a.id,version_number=n,storage_path=str(rel),content_hash=hashlib.sha256(data.text.encode()).hexdigest(),canonical_text=data.text,editor_json=data.editor_json,created_by=u.id);session.add(v);await process(session,a,v,settings.storage_root);await session.commit();return {"version_id":v.id,"number":n}
@router.post("/workspaces/{workspace_id}/commits")
async def commit(workspace_id:uuid.UUID,data:CommitIn,branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); b=await session.get(Branch,branch_id);u=await user(session);await require_workspace_role(session,workspace_id,u.id,"EDITOR")
    if not b or b.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Branch not found",404)
    state=await branch_state(session,b.head_commit_id)
    if data.artifact_version_ids: state.update(data.artifact_version_ids)
    else:
        arts=(await session.execute(select(Artifact.id).where(Artifact.workspace_id==workspace_id,Artifact.deleted_at==None))).scalars()
        for aid in arts:
            v=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==aid).order_by(desc(ArtifactVersion.version_number)))).scalars().first(); state[aid]=v.id
    c=await create_commit(session,workspace_id,b,u.id,data.message,state);session.add(ActivityEvent(workspace_id=workspace_id,actor_id=u.id,event_type="commit_created",payload={"commit_id":str(c.id)}));await session.commit();return {"id":c.id,"short_hash":c.short_hash}
@router.get("/workspaces/{workspace_id}/commits")
async def commits(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); rows=(await session.execute(select(Commit).where(Commit.workspace_id==workspace_id).order_by(desc(Commit.created_at)))).scalars();return [{"id":c.id,"message":c.message,"short_hash":c.short_hash,"created_at":c.created_at,"author_id":c.author_id} for c in rows]
@router.get("/commits/{commit_id}")
async def commit_detail(commit_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    c=await session.get(Commit,commit_id)
    if not c:err("COMMIT_NOT_FOUND","Commit not found",404)
    u=await user(session); await require_workspace_member(session,c.workspace_id,u.id)
    parents=list((await session.execute(select(CommitParent.parent_id).where(CommitParent.commit_id==c.id))).scalars());state=await branch_state(session,c.id);return {"id":c.id,"message":c.message,"parents":parents,"state":state,"created_at":c.created_at}
@router.post("/workspaces/{workspace_id}/branches")
async def create_branch(workspace_id:uuid.UUID,data:BranchIn,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id);u=await user(session);await require_workspace_role(session,workspace_id,u.id,"EDITOR"); source=await session.get(Branch,data.source_branch_id) if data.source_branch_id else (await session.execute(select(Branch).where(Branch.workspace_id==workspace_id,Branch.name=="main"))).scalar_one()
    if not source or source.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Source branch not found",404)
    b=Branch(workspace_id=workspace_id,name=data.name,head_commit_id=source.head_commit_id,created_by=u.id);session.add(b);session.add(ActivityEvent(workspace_id=workspace_id,actor_id=u.id,event_type="branch_created",payload={"branch":data.name}));await session.commit();return {"id":b.id,"name":b.name,"head_commit_id":b.head_commit_id}
@router.get("/workspaces/{workspace_id}/branches")
async def branches(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); rows=(await session.execute(select(Branch).where(Branch.workspace_id==workspace_id))).scalars();return [{"id":b.id,"name":b.name,"head_commit_id":b.head_commit_id,"protected":b.is_protected} for b in rows]
@router.get("/workspaces/{workspace_id}/compare")
async def compare(workspace_id:uuid.UUID,source_branch_id:uuid.UUID,target_branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); s=await session.get(Branch,source_branch_id);t=await session.get(Branch,target_branch_id)
    if not s or not t:err("BRANCH_NOT_FOUND","Branch not found",404)
    ss,ts=await branch_state(session,s.head_commit_id),await branch_state(session,t.head_commit_id); changes=[]
    for aid in set(ss)|set(ts):
        if ss.get(aid)!=ts.get(aid):
            vs=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.id.in_([x for x in [ss.get(aid),ts.get(aid)] if x])))).scalars().all(); texts={v.id:v.canonical_text for v in vs};changes.append({"artifact_id":aid,"kind":"ADDED" if aid not in ts else "REMOVED" if aid not in ss else "MODIFIED","diff":structural_diff(texts.get(ts.get(aid),""),texts.get(ss.get(aid),""))})
    return {"source":s.name,"target":t.name,"changes":changes}
@router.post("/workspaces/{workspace_id}/merge")
async def merge(workspace_id:uuid.UUID,data:MergeIn,session:AsyncSession=Depends(get_session)):
    u=await user(session);await require_workspace_role(session,workspace_id,u.id,"EDITOR");s=await session.get(Branch,data.source_branch_id);t=await session.get(Branch,data.target_branch_id)
    if not s or not t or s.workspace_id!=workspace_id or t.workspace_id!=workspace_id:err("BRANCH_NOT_FOUND","Branch not found",404)
    result,conflicts,_=await plan_merge(session,t,s);m=Merge(workspace_id=workspace_id,source_branch_id=s.id,target_branch_id=t.id,created_by=u.id);session.add(m);await session.flush()
    for x in conflicts: session.add(MergeConflict(merge_id=m.id,artifact_id=x["artifact_id"],base_text=x["base"],target_text=x["target"],source_text=x["source"]))
    if conflicts: m.status="CONFLICT";await session.commit();return {"merge_id":m.id,"status":"CONFLICT","conflicts":len(conflicts)}
    c=await create_commit(session,workspace_id,t,u.id,f"Merge {s.name} into {t.name}",result,s.head_commit_id);m.status="COMPLETED";m.merge_commit_id=c.id;await session.commit();return {"merge_id":m.id,"status":"COMPLETED","commit_id":c.id}
@router.post("/merge-conflicts/{conflict_id}/resolve")
async def resolve(conflict_id:uuid.UUID,data:ResolveIn,session:AsyncSession=Depends(get_session)):
    c=await session.get(MergeConflict,conflict_id)
    if not c:err("CONFLICT_NOT_FOUND","Conflict not found",404)
    merge_record=await session.get(Merge,c.merge_id);u=await user(session);await require_workspace_role(session,merge_record.workspace_id,u.id,"EDITOR")
    c.resolved_text=data.target_text if data.resolution=="TARGET" else c.source_text if data.resolution=="SOURCE" else data.text
    if not c.resolved_text:err("INVALID_RESOLUTION","Manual resolution requires text")
    c.resolved_at=datetime.utcnow();await session.commit();return {"id":c.id,"resolved":True}

@router.get("/merges/{merge_id}")
async def merge_detail(merge_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    merge_record=await session.get(Merge,merge_id)
    if not merge_record:err("MERGE_NOT_FOUND","Merge not found.",404)
    u=await user(session);await require_workspace_member(session,merge_record.workspace_id,u.id);conflicts=(await session.execute(select(MergeConflict).where(MergeConflict.merge_id==merge_id))).scalars().all();return {"id":str(merge_record.id),"status":merge_record.status,"source_branch_id":str(merge_record.source_branch_id),"target_branch_id":str(merge_record.target_branch_id),"conflicts":[{"id":str(conflict.id),"artifact_id":str(conflict.artifact_id),"base":conflict.base_text,"target":conflict.target_text,"source":conflict.source_text,"resolved_text":conflict.resolved_text,"resolved_at":conflict.resolved_at} for conflict in conflicts]}

@router.post("/merges/{merge_id}/complete")
async def complete_merge(merge_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    merge_record=await session.get(Merge,merge_id)
    if not merge_record:err("MERGE_NOT_FOUND","Merge not found.",404)
    u=await user(session);await require_workspace_role(session,merge_record.workspace_id,u.id,"EDITOR")
    conflicts=(await session.execute(select(MergeConflict).where(MergeConflict.merge_id==merge_id))).scalars().all()
    if any(not conflict.resolved_at for conflict in conflicts):err("UNRESOLVED_CONFLICTS","Resolve every conflict before completing the merge.",409)
    target=await session.get(Branch,merge_record.target_branch_id);source=await session.get(Branch,merge_record.source_branch_id);result,_,_=await plan_merge(session,target,source)
    for conflict in conflicts:
        artifact=await session.get(Artifact,conflict.artifact_id);last=(await session.execute(select(ArtifactVersion).where(ArtifactVersion.artifact_id==artifact.id).order_by(desc(ArtifactVersion.version_number)))).scalars().first();number=last.version_number+1;rel=Path("workspaces")/str(artifact.workspace_id)/"artifacts"/str(artifact.id)/"versions"/f"v{number}"/artifact.original_filename;path=settings.storage_root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(conflict.resolved_text);version=ArtifactVersion(artifact_id=artifact.id,version_number=number,storage_path=str(rel),content_hash=hashlib.sha256(conflict.resolved_text.encode()).hexdigest(),canonical_text=conflict.resolved_text,created_by=u.id);session.add(version);await session.flush();await process(session,artifact,version,settings.storage_root);result[artifact.id]=version.id
    commit_record=await create_commit(session,merge_record.workspace_id,target,u.id,f"Merge {source.name} into {target.name}",result,source.head_commit_id);merge_record.status="COMPLETED";merge_record.merge_commit_id=commit_record.id;session.add(ActivityEvent(workspace_id=merge_record.workspace_id,actor_id=u.id,event_type="merge_completed",payload={"merge_id":str(merge_record.id),"commit_id":str(commit_record.id)}));await session.commit();return {"merge_id":str(merge_record.id),"status":"COMPLETED","commit_id":str(commit_record.id)}
@router.post("/workspaces/{workspace_id}/chats")
async def create_chat(workspace_id:uuid.UUID,data:ChatIn,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id);u=await user(session);await require_workspace_role(session,workspace_id,u.id,"EDITOR");b=await session.get(Branch,data.branch_id) if data.branch_id else (await session.execute(select(Branch).where(Branch.workspace_id==workspace_id,Branch.name=="main"))).scalar_one();c=ResearchChat(workspace_id=workspace_id,title=data.title,created_by=u.id,active_branch_id=b.id);session.add(c);await session.commit();return {"id":c.id,"title":c.title,"branch_id":b.id}
@router.get("/workspaces/{workspace_id}/chats")
async def chats(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); rows=(await session.execute(select(ResearchChat).where(ResearchChat.workspace_id==workspace_id))).scalars();return [{"id":c.id,"title":c.title,"branch_id":c.active_branch_id} for c in rows]
@router.post("/workspaces/{workspace_id}/chats/{chat_id}/query")
async def query(workspace_id:uuid.UUID,chat_id:uuid.UUID,data:QueryIn,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); chat=await session.get(ResearchChat,chat_id)
    if not chat or chat.workspace_id!=workspace_id:err("CHAT_NOT_FOUND","Research chat not found",404)
    session.add(ChatMessage(chat_id=chat_id,role="user",content=data.message)); text,cites=await answer(session,workspace_id,chat_id,data.branch_id,data.message,data.context);session.add(ChatMessage(chat_id=chat_id,role="assistant",content=text,citations=cites));await session.commit()
    async def events():
        yield "event: citations\ndata: "+json.dumps(cites)+"\n\n"
        for piece in text.split(" "): yield "event: token\ndata: "+json.dumps(piece+" ")+"\n\n"
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(events(),media_type="text/event-stream")
@router.get("/workspaces/{workspace_id}/search")
async def global_search(workspace_id:uuid.UUID,q:str,branch_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); b=await session.get(Branch,branch_id);rows=await answer # re-use retrieval directly
    from researchgit.retrieval.hybrid_search import search
    found=await search(session,workspace_id,list((await branch_state(session,b.head_commit_id)).values()),q)
    return [{"artifact_id":str(a.id),"artifact":a.name,"text":c.content[:300],"page":c.page_number,"version_id":str(c.artifact_version_id)} for _,c,a in found]
@router.get("/workspaces/{workspace_id}/activity")
async def activity(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    await workspace_or_404(session,workspace_id); rows=(await session.execute(select(ActivityEvent).where(ActivityEvent.workspace_id==workspace_id).order_by(desc(ActivityEvent.created_at)))).scalars();return [{"type":x.event_type,"payload":x.payload,"created_at":x.created_at} for x in rows]
@router.post("/workspaces/{workspace_id}/seen")
async def mark_seen(workspace_id:uuid.UUID,session:AsyncSession=Depends(get_session)):
    u=await user(session); await workspace_or_404(session,workspace_id);state=(await session.execute(select(UserWorkspaceState).where(UserWorkspaceState.user_id==u.id,UserWorkspaceState.workspace_id==workspace_id))).scalar_one_or_none()
    latest=(await session.execute(select(Commit).where(Commit.workspace_id==workspace_id).order_by(desc(Commit.created_at)))).scalars().first()
    since=state.last_seen_at if state else None; q=select(func.count(Commit.id)).where(Commit.workspace_id==workspace_id)
    if since:q=q.where(Commit.created_at>since)
    count=(await session.execute(q)).scalar_one()
    if not state:state=UserWorkspaceState(user_id=u.id,workspace_id=workspace_id);session.add(state)
    state.last_seen_at=datetime.utcnow();state.last_seen_commit_id=latest.id if latest else None;await session.commit();return {"commits_since_last_seen":count,"last_seen_at":since}
