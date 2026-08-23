"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";

export default function Register() {
  const router=useRouter(); const [name,setName]=useState(""); const [email,setEmail]=useState(""); const [password,setPassword]=useState(""); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(event:FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await api("/api/auth/register",{method:"POST",body:JSON.stringify({name,email,password})}); router.replace("/workspaces"); } catch (cause) { setError(cause instanceof Error ? cause.message : "Account creation failed."); } finally { setBusy(false); } }
  return <main className="max-w-md mx-auto p-10"><h1 className="text-3xl font-semibold">Create your account</h1><p className="muted mt-2">Start a secure, collaborative research workspace.</p><form className="panel p-5 mt-7 grid gap-3" onSubmit={submit}><label>Name<input className="border rounded px-3 py-2 w-full mt-1" value={name} onChange={e=>setName(e.target.value)} required /></label><label>Email<input className="border rounded px-3 py-2 w-full mt-1" type="email" value={email} onChange={e=>setEmail(e.target.value)} required /></label><label>Password <span className="muted">(10+ characters)</span><input className="border rounded px-3 py-2 w-full mt-1" type="password" minLength={10} value={password} onChange={e=>setPassword(e.target.value)} required /></label>{error&&<p className="text-red-700 text-sm">{error}</p>}<button className="btn btn-primary" disabled={busy}>{busy?"Creating…":"Create account"}</button></form><p className="mt-4 muted">Already a member? <Link className="text-emerald-700" href="/login">Sign in</Link></p></main>;
}
