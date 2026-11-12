import assert from 'node:assert/strict'
import { test } from 'node:test'
import { listCandidates, activeOverview, activeOptions, createActiveTask, confirmReview, prepareActiveTraining, activeComparison } from '../src/api/active-learning.ts'

test('candidate filters omit empty booleans and preserve server pagination', async () => {
  const original = globalThis.fetch
  let seen
  globalThis.fetch = async url => { seen=String(url);return Response.json({items:[],total:81,page:2,pageSize:12}) }
  try {
    const result=await listCandidates('job',new URLSearchParams({purpose:'training',page:'2',page_size:'12',selected:'',reason:''}))
    const url=new URL(seen,'http://localhost')
    assert.equal(url.searchParams.has('selected'),false)
    assert.equal(url.searchParams.has('reason'),false)
    assert.equal(url.searchParams.get('page'),'2')
    assert.equal(result.total,81)
  } finally {globalThis.fetch=original}
})

test('overview and diagnostic options use actual backend response fields', async () => {
  const original=globalThis.fetch
  globalThis.fetch=async url=>Response.json(String(url).endsWith('/overview')
    ? {activeIterations:2,pending:9,reviewed:4,awaitingEvaluation:1}
    : {models:[],datasets:[],devices:[],evaluations:[{id:'e1',versionId:'v1',config:{purpose:'diagnostic'}}]})
  try {
    assert.deepEqual(await activeOverview(),{activeIterations:2,pending:9,reviewed:4,awaitingEvaluation:1,pendingReview:9,pendingEvaluation:1})
    const options=await activeOptions()
    assert.equal(options.evaluations[0].purpose,'diagnostic')
    assert.equal(options.evaluations[0].status,'succeeded')
  } finally {globalThis.fetch=original}
})

test('task and review mutations preserve threshold, version, and explicit negative confirmation', async () => {
  const original=globalThis.fetch, requests=[]
  globalThis.fetch=async (url,init)=>{requests.push({url:String(url),body:JSON.parse(init.body),headers:init.headers});return Response.json({id:'created'})}
  try {
    await createActiveTask({iterationId:'i',strategy:'low_confidence',retainConfidence:.05,minConfidence:.1,maxConfidence:.5,includeNoPredictions:true},'key')
    await confirmReview('sample',{version:7,annotations:[],status:'negative',negativeConfirmed:true})
    assert.equal(requests[0].body.retainConfidence,.05)
    assert.equal(requests[0].body.minConfidence,.1)
    assert.equal(requests[0].headers['Idempotency-Key'],'key')
    assert.deepEqual(requests[1].body,{version:7,annotations:[],status:'negative',negativeConfirmed:true})
  } finally {globalThis.fetch=original}
})

test('preflight and comparison preserve current contracts and missing metrics', async () => {
  const original=globalThis.fetch
  globalThis.fetch=async url=>Response.json(String(url).endsWith('/prepare-training')
    ? {ready:true,manifestId:'m',manifestDigest:'digest',counts:{total:12},issues:[],checks:[{code:'versions',label:'版本一致',passed:true}]}
    : {comparable:false,reasons:['协议不一致'],rows:[{key:'maskMap50_95',label:'Mask mAP50-95',baseline:null,result:.4,delta:null}]})
  try {
    assert.equal((await prepareActiveTraining('i')).checks[0].passed,true)
    const result=await activeComparison('i')
    assert.equal(result.rows[0].baseline,null)
    assert.equal(result.rows[0].result,.4)
    assert.equal(result.rows[0].delta,null)
  } finally {globalThis.fetch=original}
})

test('version conflicts surface actionable backend message', async () => {
  const original=globalThis.fetch
  globalThis.fetch=async ()=>Response.json({detail:'标注版本发生变化，请重新加载并确认'},{status:409})
  try {await assert.rejects(()=>confirmReview('x',{version:1,annotations:[],status:'negative',negativeConfirmed:true}),/标注版本发生变化/)}
  finally {globalThis.fetch=original}
})
