"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";

export default function Login() {
  const router=useRouter(); const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(event:FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await api("/api/auth/login",{method:"POST",body:JSON.stringify({email,password})}); router.replace(new URLSearchParams(window.location.search).get("next")||"/workspaces"); } catch (cause) { setError(cause instanceof Error ? cause.message : "Sign in failed."); } finally { setBusy(false); } }
  return <main className="max-w-md mx-auto p-10"><h1 className="text-3xl font-semibold">Welcome to ResearchGit</h1><p className="muted mt-2">Sign in to your collaborative research workspaces.</p><form className="panel p-5 mt-7 grid gap-3" onSubmit={submit}><label>Email<input className="border rounded px-3 py-2 w-full mt-1" type="email" value={email} onChange={e=>setEmail(e.target.value)} required /></label><label>Password<input className="border rounded px-3 py-2 w-full mt-1" type="password" value={password} onChange={e=>setPassword(e.target.value)} required /></label>{error&&<p className="text-red-700 text-sm">{error}</p>}<button className="btn btn-primary" disabled={busy}>{busy?"Signing in…":"Sign in"}</button></form><p className="mt-4 muted">New here? <Link className="text-emerald-700" href="/register">Create an account</Link></p></main>;
}
