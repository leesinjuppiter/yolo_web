import type { SelectableDatasetTask } from '../domain'
export interface ModelVersion {
 id:string; name:string; displayName:string; description?:string; version:string; taskType:SelectableDatasetTask
 taskId:string; sourceTaskId:string; datasetId:string; datasetName:string; snapshotDigest:string; sha256:string; createdAt:string
 lifecycle:string; trainingMetrics:Record<string,number>; validationStatus:string; evaluation:ModelJob|null; actions:string[]
 config?:import('./training').TrainingConfig; artifacts?:unknown[]; evaluations?:ModelJob[]
}
export interface ModelJob {
 id:string; versionId:string; exportId?:string; status:string; phase:string; config:Record<string,unknown>
 createdAt:string; finishedAt?:string; error:string|null; report:Record<string,unknown>|null; downloadUrl?:string|null
 manifest?:Record<string,unknown>; logs?:JobLog[]
}
export interface JobLog {sequence:number; level:string; message:string; time?:string}
export interface JobList {items:ModelJob[]; total?:number; page?:number; pageSize?:number}
export interface RegistryList {items:ModelVersion[]; total:number; page:number; pageSize:number; summary:{total:number;archived:number;evaluated:number}}
export interface Comparison {models:ModelVersion[];baselineId:string;comparable:boolean;reasons:string[];rows:{key:string;label:string;unit:string;values:Record<string,number|null>;deltas:Record<string,number|null>}[]}
export const jobLabels:Record<string,string>={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',canceled:'已取消'}
export const formatDate=(value?:string)=>value?new Date(value).toLocaleString('zh-CN'):'—'
export const formatValue=(value:unknown)=>typeof value==='number'?Number(value.toFixed(4)).toString():value==null?'—':String(value)
