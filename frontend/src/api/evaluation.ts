import { modelRequest,jsonPost } from './models'
import type { ModelJob,JobList,JobLog } from '../types/models'
export const evaluateModel=(versionId:string,imgsz:number,key?:string)=>modelRequest<ModelJob>('/api/evaluations',jsonPost({versionId,imgsz,deviceId:'cpu'},key))
export const listEvaluations=(signal?:AbortSignal)=>modelRequest<JobList>('/api/evaluations',{signal})
export const getEvaluation=(id:string,signal?:AbortSignal)=>modelRequest<ModelJob>('/api/evaluations/'+encodeURIComponent(id),{signal})
export const evaluationLogs=(id:string,signal?:AbortSignal)=>modelRequest<{items:JobLog[]}>('/api/evaluations/'+encodeURIComponent(id)+'/logs',{signal})
export const cancelEvaluation=(id:string)=>modelRequest<ModelJob>('/api/evaluations/'+encodeURIComponent(id)+'/cancel',jsonPost({}))
