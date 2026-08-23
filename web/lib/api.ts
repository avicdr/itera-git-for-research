const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
export async function api<T>(path:string,init?:RequestInit):Promise<T>{const r=await fetch(API+path,{...init,credentials:"include",headers:{"Content-Type":"application/json",...(init?.headers||{})},cache:"no-store"});if(!r.ok){const error:any=new Error((await r.json().catch(()=>null))?.detail?.error?.message||"Request failed");error.status=r.status;throw error}return r.json()}
export {API};
