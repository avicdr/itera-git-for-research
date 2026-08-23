"use client";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Collaboration from "@tiptap/extension-collaboration";
import CollaborationCursor from "@tiptap/extension-collaboration-cursor";
import * as Y from "yjs";
import { WebsocketProvider } from "y-websocket";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, API } from "@/lib/api";

export default function DocumentEditor({ artifactId, initial }: { artifactId: string; initial: string }) {
  const [state,setState]=useState("Connecting collaborators…"), saveTimer=useRef<ReturnType<typeof setTimeout> | null>(null);
  const document=useMemo(()=>new Y.Doc(),[]);
  const provider=useMemo(()=>new WebsocketProvider(API.replace(/^http/,"ws"),`api/collaboration/document-${artifactId}`,document,{connect:false}),[artifactId,document]);
  const editor=useEditor({extensions:[StarterKit.configure({history:false}),Link,Collaboration.configure({document}),CollaborationCursor.configure({provider,user:{name:"Researcher",color:"#047857"}})],content:undefined,onUpdate:({editor:changed})=>{setState("Saving collaborative changes…");if(saveTimer.current)clearTimeout(saveTimer.current);saveTimer.current=setTimeout(async()=>{try{await api(`/api/artifacts/${artifactId}/document`,{method:"PUT",body:JSON.stringify({text:changed.getText(),editor_json:changed.getJSON()})});setState("Autosaved ✓ · collaboration synced")}catch{setState("Couldn’t save changes. Reconnecting…")}},900)}});
  useEffect(()=>{let seeded=false;const seed=()=>{if(seeded||document.getXmlFragment("default").length)return;seeded=true;editor?.commands.setContent(initial)};provider.on("status",({status}:{status:string})=>setState(status==="connected"?"Collaborators connected · autosaved ✓":"Reconnecting collaboration…"));provider.on("sync",seed);provider.connect();api<any>("/api/auth/me").then(result=>provider.awareness.setLocalStateField("user",{name:result.user.name,color:"#047857"})).catch(()=>{});const fallback=window.setTimeout(seed,600);return()=>{window.clearTimeout(fallback);if(saveTimer.current)clearTimeout(saveTimer.current);provider.disconnect();provider.destroy();document.destroy()}},[document,editor,initial,provider]);
  async function commentOnSelection(){if(!editor)return;const {from,to}=editor.state.selection;const selected=editor.state.doc.textBetween(from,to," ").trim();if(!selected){setState("Select text before starting a comment.");return}const content=window.prompt("Start a research discussion about this text:");if(!content?.trim())return;try{await api(`/api/artifacts/${artifactId}/comments`,{method:"POST",body:JSON.stringify({selected_text:selected,anchor:{from,to},content})});setState("Comment added for collaborators.")}catch{setState("Couldn’t create comment.")}}
  if(!editor)return null;return <><div className="flex gap-1 mb-3"><button className="btn" onClick={()=>editor.chain().focus().toggleBold().run()}>Bold</button><button className="btn" onClick={()=>editor.chain().focus().toggleItalic().run()}>Italic</button><button className="btn" onClick={()=>editor.chain().focus().toggleBulletList().run()}>List</button><button className="btn" onClick={commentOnSelection}>Comment</button><span className="muted ml-auto">{state}</span></div><div className="panel p-7 min-h-[60vh] prose max-w-none"><EditorContent editor={editor}/></div></>;
}
