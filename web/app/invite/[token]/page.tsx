"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function AcceptInvite() {
  const {token}=useParams<{token:string}>(); const router=useRouter(); const [invite,setInvite]=useState<any>(); const [error,setError]=useState(""); const [joining,setJoining]=useState(false);
  useEffect(()=>{api<any>(`/api/invites/${token}`).then(setInvite).catch((cause:any)=>{if(cause.status===401) router.replace(`/login?next=${encodeURIComponent(`/invite/${token}`)}`); else setError(cause.message||"This invite is unavailable.")})},[router,token]);
  async function join(){setJoining(true);try{const result=await api<any>(`/api/invites/${token}/accept`,{method:"POST"});router.replace(`/workspace/${result.workspace_id}`)}catch(cause){setError(cause instanceof Error?cause.message:"Could not accept invite.");setJoining(false)}}
  return <main className="max-w-lg mx-auto p-10"><section className="panel p-7"><h1 className="text-2xl font-semibold">Join a research workspace</h1>{invite&&<><p className="mt-3">You’ve been invited to <b>{invite.workspace_name}</b> as an <b>{invite.role.toLowerCase()}</b>.</p><button className="btn btn-primary mt-6" disabled={joining} onClick={join}>{joining?"Joining…":"Join workspace"}</button></>}{!invite&&!error&&<p className="muted mt-3">Checking invite…</p>}{error&&<p className="text-red-700 mt-3">{error}</p>}</section></main>;
}
