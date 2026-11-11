import type { RegistryList,ModelVersion,Comparison } from '../types/models'
import { createUuid } from '../utils/id'
export async function modelRequest<T>(url:string,init?:RequestInit):Promise<T>{
 const response=await fetch(url,{cache:'no-store',...init})
 if(!response.ok){
  const body=await response.json().catch(()=>null), detail=body?.detail
  throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(x=>x.msg).join('；'):detail?.message||'操作失败（HTTP '+response.status+'）')
 }
 if(response.status===204)return undefined as T
 return response.json()
}
export const jsonPost=(body:unknown,key:string=createUuid()):RequestInit=>({method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)})
export const listModels=(params:URLSearchParams,signal?:AbortSignal)=>modelRequest<RegistryList>('/api/models?'+params,{signal})
export const getModel=(id:string,signal?:AbortSignal)=>modelRequest<ModelVersion>('/api/models/'+encodeURIComponent(id),{signal})
export const deleteModel=(id:string)=>modelRequest<void>('/api/models/'+encodeURIComponent(id),{method:'DELETE'})
export const updateModel=(id:string,body:{displayName:string;description:string})=>modelRequest<ModelVersion>('/api/models/'+encodeURIComponent(id),{...jsonPost(body),method:'PATCH'})
export const archiveModel=(id:string,restore:boolean)=>modelRequest<ModelVersion>('/api/models/'+encodeURIComponent(id)+(restore?'/restore':'/archive'),jsonPost({}))
export const compareModels=(versionIds:string[],baselineId:string,signal?:AbortSignal)=>modelRequest<Comparison>('/api/models/compare',{...jsonPost({versionIds,baselineId}),signal})
