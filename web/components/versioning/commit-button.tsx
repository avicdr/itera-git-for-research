"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api"; import {useBranchStore} from "@/stores/branch-store";
export default function CommitButton({workspaceId}:{workspaceId:string}) {
  const [open,setOpen]=useState(false),[message,setMessage]=useState(""); const qc=useQueryClient();
  const branches=useQuery({queryKey:["branches",workspaceId],queryFn:()=>api<any[]>(`/api/workspaces/${workspaceId}/branches`)});
  const selected=useBranchStore(s=>s.selected[workspaceId]); const branch=branches.data?.find(x=>x.id===selected)||branches.data?.[0];
  const changes=useQuery({queryKey:["changes",workspaceId,branch?.id],enabled:!!branch,queryFn:()=>api<any>(`/api/workspaces/${workspaceId}/working-changes?branch_id=${branch.id}`)});
  const commit=useMutation({mutationFn:()=>api(`/api/workspaces/${workspaceId}/commits?branch_id=${branch.id}`,{method:"POST",body:JSON.stringify({message})}),onSuccess:()=>{setOpen(false);setMessage("");qc.invalidateQueries({queryKey:["changes",workspaceId]});qc.invalidateQueries({queryKey:["commits",workspaceId]});qc.invalidateQueries({queryKey:["branches",workspaceId]})}});
  return <><button className="btn btn-primary" onClick={()=>setOpen(true)}>Commit{changes.data?.changes?.length?` (${changes.data.changes.length})`:""}</button>{open&&<div className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center"><div className="panel p-5 w-[430px]"><h2 className="font-semibold text-lg">Commit changes to {branch?.name||"branch"}</h2><p className="muted mt-1">{changes.data?.changes?.length||0} changed artifact(s) will become an immutable snapshot.</p><div className="mt-3 max-h-40 overflow-auto text-sm">{changes.data?.changes?.map((x:any)=><p key={x.artifact_id}>{x.kind} {x.name}</p>)}</div><input className="border rounded w-full p-2 mt-4" value={message} onChange={e=>setMessage(e.target.value)} placeholder="Describe this research checkpoint"/><p className="text-red-700 text-sm mt-2">{commit.error?.message}</p><div className="flex justify-end gap-2 mt-4"><button className="btn" onClick={()=>setOpen(false)}>Cancel</button><button disabled={!message.trim()||!changes.data?.changes?.length||commit.isPending} className="btn btn-primary" onClick={()=>commit.mutate()}>Create commit</button></div></div></div>}</>;
}
