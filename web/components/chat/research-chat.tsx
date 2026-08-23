"use client";

import { useEffect, useState } from "react";
import { api, API } from "@/lib/api";

type Chat = { id: string; title: string; branch_id: string };
type Branch = { id: string; name: string };

export default function ResearchChat({ workspaceId }: { workspaceId: string }) {
  const [chats, setChats] = useState<Chat[]>([]); const [branches, setBranches] = useState<Branch[]>([]);
  const [branch, setBranch] = useState(""); const [chat, setChat] = useState(""); const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState(""); const [sources, setSources] = useState<any[]>([]); const [error, setError] = useState(""); const [creating, setCreating] = useState(true);
  async function createChat(branchId: string, title = "Research chat") {
    const created = await api<Chat>(`/api/workspaces/${workspaceId}/chats`, { method: "POST", body: JSON.stringify({ title, branch_id: branchId }) });
    setChats(current => [...current, created]); setChat(created.id); setBranch(created.branch_id || branchId); return created;
  }
  useEffect(() => { let active = true; async function initialise() { setCreating(true); setError(""); try {
    const [existingChats, availableBranches] = await Promise.all([api<Chat[]>(`/api/workspaces/${workspaceId}/chats`), api<Branch[]>(`/api/workspaces/${workspaceId}/branches`)]);
    if (!active) return; setBranches(availableBranches); const defaultBranch = availableBranches[0]?.id; if (!defaultBranch) throw new Error("This workspace has no branch yet.");
    setBranch(existingChats[0]?.branch_id || defaultBranch); if (existingChats.length) { setChats(existingChats); setChat(existingChats[0].id); } else await createChat(defaultBranch);
  } catch (cause) { if (active) setError(cause instanceof Error ? cause.message : "Could not initialise research chat."); } finally { if (active) setCreating(false); } } initialise(); return () => { active = false; }; }, [workspaceId]);
  async function ask() { if (!message.trim() || !chat || !branch) return; setError(""); setAnswer(""); setSources([]); try {
    const response = await fetch(`${API}/api/workspaces/${workspaceId}/chats/${chat}/query`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, branch_id: branch, context: { documents: true, pdfs: true, chat_exports: true } }) });
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail?.error?.message || "Research AI request failed."); const reader = response.body?.getReader(); if (!reader) throw new Error("The answer stream did not start."); const decode = new TextDecoder(); let buffer = "";
    while (true) { const next = await reader.read(); if (next.done) break; buffer += decode.decode(next.value, { stream: true }); const events = buffer.split("\n\n"); buffer = events.pop() || ""; for (const event of events) { const raw = event.split("\ndata: ")[1]; if (!raw) continue; const value = JSON.parse(raw); if (event.startsWith("event: token")) setAnswer(x => x + value); if (event.startsWith("event: citations")) setSources(value); } }
    setMessage("");
  } catch (cause) { setError(cause instanceof Error ? cause.message : "Research AI request failed."); } }
  return <div className="p-4 h-full flex flex-col gap-3"><div className="flex justify-between"><div><b>RESEARCH AI</b><p className="muted">Current branch context</p></div><button className="btn text-xs" disabled={!branches.length} onClick={() => createChat(branch, `Research chat ${chats.length + 1}`)}>New chat</button></div><select aria-label="Research chat" className="btn w-full" value={chat} disabled={creating} onChange={e => { const next = chats.find(x => x.id === e.target.value); setChat(e.target.value); if (next?.branch_id) setBranch(next.branch_id); }}>{creating ? <option>Preparing chat…</option> : chats.map(x => <option value={x.id} key={x.id}>{x.title}</option>)}</select><select aria-label="Research branch" className="btn w-full text-sm" value={branch} disabled={creating} onChange={e => setBranch(e.target.value)}>{branches.map(x => <option value={x.id} key={x.id}>Branch: {x.name}</option>)}</select><div className="flex-1 whitespace-pre-wrap text-sm overflow-auto">{answer || <span className="muted">Ask a question about sources visible from this branch.</span>}</div>{error && <p className="text-sm text-red-700">{error}</p>}{sources.length > 0 && <div className="text-xs"><b>Sources</b>{sources.map(s => <div key={s.chunk_id} className="mt-1 text-emerald-800">[{s.source_id}] {s.artifact_name}{s.page ? ` · p. ${s.page}` : ""}</div>)}</div>}<textarea className="border rounded p-2 text-sm" value={message} onChange={e => setMessage(e.target.value)} placeholder="Ask research AI…" disabled={creating}/><button onClick={ask} className="btn btn-primary" disabled={creating || !message.trim() || !chat}>Ask</button></div>;
}
