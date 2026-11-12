import { modelRequest,jsonPost } from './models'
import type { ModelJob,JobList } from '../types/models'
export type JobResource='exports'|'deployment-packages'
export const createExport=(versionId:string,imgsz:number,key?:string)=>modelRequest<ModelJob>('/api/exports',jsonPost({versionId,imgsz,deviceId:'cpu'},key))
export const createPackage=(exportId:string,key?:string)=>modelRequest<ModelJob>('/api/deployment-packages',jsonPost({exportId},key))
export const listModelJobs=(resource:JobResource,signal?:AbortSignal,page=1)=>modelRequest<JobList>('/api/'+resource+'?page='+page+'&page_size=20',{signal})
export const getModelJob=(resource:JobResource,id:string,signal?:AbortSignal)=>modelRequest<ModelJob>('/api/'+resource+'/'+encodeURIComponent(id),{signal})
export const cancelModelJob=(resource:JobResource,id:string)=>modelRequest<ModelJob>('/api/'+resource+'/'+encodeURIComponent(id)+'/cancel',jsonPost({}))
