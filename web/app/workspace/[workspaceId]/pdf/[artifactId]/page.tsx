"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Shell from "@/components/workspace/shell";
import { API } from "@/lib/api";

type PdfDocument = import("pdfjs-dist").PDFDocumentProxy;

export default function PdfPage() {
  const { workspaceId, artifactId } = useParams<{ workspaceId: string; artifactId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const documentRef = useRef<PdfDocument | null>(null);
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(0);
  const [scale, setScale] = useState(1.2);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fileUrl = `${API}/api/artifacts/${artifactId}/file`;

  const goToPage = useCallback((next: number) => {
    const safe = Math.min(Math.max(1, next), pageCount || 1);
    setPage(safe);
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(safe));
    router.replace(`/workspace/${workspaceId}/pdf/${artifactId}?${params.toString()}`, { scroll: false });
  }, [artifactId, pageCount, router, searchParams, workspaceId]);

  useEffect(() => {
    const requested = Number(searchParams.get("page"));
    if (Number.isInteger(requested) && requested > 0) setPage(requested);
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true); setError(null);
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
        const response = await fetch(fileUrl, { credentials: "include" });
        if (!response.ok) throw new Error(response.status === 404 ? "The original PDF is unavailable." : "You do not have permission to view this PDF.");
        const pdf = await pdfjs.getDocument({ data: await response.arrayBuffer() }).promise;
        if (!cancelled) { documentRef.current = pdf; setPageCount(pdf.numPages); setPage((current) => Math.min(Math.max(1, current), pdf.numPages)); }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? `Couldn’t render this PDF: ${cause.message}` : "Couldn’t render this PDF.");
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; documentRef.current = null; };
  }, [fileUrl]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const pdf = documentRef.current, canvas = canvasRef.current;
      if (!pdf || !canvas || !page) return;
      try {
        const pdfPage = await pdf.getPage(page); const viewport = pdfPage.getViewport({ scale }); const ratio = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * ratio); canvas.height = Math.floor(viewport.height * ratio); canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
        const context = canvas.getContext("2d"); if (!context || cancelled) return;
        await pdfPage.render({ canvas, canvasContext: context, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] }).promise;
      } catch { if (!cancelled) setError("The selected page could not be rendered."); }
    })();
    return () => { cancelled = true; };
  }, [page, scale, pageCount]);

  async function searchPdf() {
    const pdf = documentRef.current;
    if (!pdf || !query.trim()) { setMatches([]); return; }
    const found: number[] = [];
    for (let index = 1; index <= pdf.numPages; index += 1) {
      const content = await (await pdf.getPage(index)).getTextContent();
      if (content.items.some((item) => "str" in item && item.str.toLowerCase().includes(query.trim().toLowerCase()))) found.push(index);
    }
    setMatches(found); if (found[0]) goToPage(found[0]);
  }

  return <Shell workspaceId={workspaceId}>
    <div className="flex flex-wrap items-center gap-2 mb-4"><div><h1 className="text-2xl font-semibold">PDF source</h1><p className="muted">Page {page}{pageCount ? ` of ${pageCount}` : ""}</p></div><div className="ml-auto flex flex-wrap gap-2 items-center"><button className="btn" disabled={page <= 1} onClick={() => goToPage(page - 1)}>Previous</button><label className="text-sm">Page <input aria-label="Page number" className="w-16 border rounded px-2 py-1" type="number" min="1" max={pageCount || undefined} value={page} onChange={(event) => goToPage(Number(event.target.value))} /></label><button className="btn" disabled={!pageCount || page >= pageCount} onClick={() => goToPage(page + 1)}>Next</button><button className="btn" onClick={() => setScale((value) => Math.max(.6, value - .2))}>−</button><button className="btn" onClick={() => setScale((value) => Math.min(3, value + .2))}>+</button><button className="btn" onClick={() => setScale(1.2)}>Fit width</button><a className="btn" href={fileUrl} download>Download</a></div></div>
    <div className="panel p-3 mb-4 flex gap-2"><input className="flex-1 border rounded px-3 py-2" placeholder="Search this PDF" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && searchPdf()} /><button className="btn" onClick={searchPdf}>Search</button>{matches.length > 0 && <span className="muted self-center">Found on pages {matches.join(", ")}</span>}</div>
    {loading && <div className="panel p-8 text-center muted">Loading PDF…</div>}{error && <div className="panel p-8 text-center"><p className="text-red-700 mb-3">{error}</p><a className="btn" href={fileUrl} download>Download original PDF</a></div>}{!loading && !error && <div className="panel p-4 overflow-auto bg-slate-100"><canvas ref={canvasRef} className="block mx-auto bg-white shadow" aria-label={`PDF page ${page}`} /></div>}
  </Shell>;
}
