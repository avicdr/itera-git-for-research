"use client";

import { ChangeEvent, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API } from "@/lib/api";

const ACCEPTED = ".md,.txt,.pdf,.json";

export default function UploadArtifact({ workspaceId }: { workspaceId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const queryClient = useQueryClient();

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError("");
    setStatus(`Uploading ${file.name}…`);
    const form = new FormData();
    form.append("file", file);
    form.append("scope", "WORKSPACE");
    try {
      const response = await fetch(`${API}/api/workspaces/${workspaceId}/artifacts`, {
        method: "POST",
        body: form,
        credentials: "include",
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail?.error?.message ?? "Upload failed.");
      setStatus(`${file.name} is ready for research chat and commits.`);
      await queryClient.invalidateQueries({ queryKey: ["artifacts", workspaceId] });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed.");
      setStatus("");
    } finally {
      if (input.current) input.current.value = "";
    }
  }

  return <div className="panel p-4 mt-6">
    <div className="flex items-center justify-between gap-3">
      <div>
        <b>Import research artifact</b>
        <p className="muted">Markdown, text, text-extractable PDFs, or ChatGPT/Claude JSON exports.</p>
      </div>
      <button className="btn btn-primary" onClick={() => input.current?.click()}>Upload file</button>
      <input ref={input} className="hidden" type="file" accept={ACCEPTED} onChange={upload} />
    </div>
    {status && <p className="text-sm text-emerald-700 mt-3">{status}</p>}
    {error && <p className="text-sm text-red-700 mt-3">{error}</p>}
  </div>;
}
