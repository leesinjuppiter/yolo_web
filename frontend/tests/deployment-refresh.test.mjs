import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { test } from 'node:test'
import { createRenderer, defineComponent, h, KeepAlive, reactive, nextTick } from 'vue'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const file = new URL('../src/pages/DeploymentCenterView.vue', import.meta.url)
const { descriptor } = parse(readFileSync(file, 'utf8'))
const script = compileScript(descriptor, { id: 'deployment-refresh-test' }).content
const moduleUrl = text => 'data:text/javascript;base64,' + Buffer.from(text).toString('base64')
const api = names => moduleUrl(names.map(name => `export const ${name}=(...args)=>globalThis.deploymentFixture.call('${name}',args)`).join('\n'))
const changes = pathToFileURL(require.resolve('../src/api/changes.ts')).href
const imports = {
  vue: pathToFileURL(require.resolve('vue')).href,
  'vue-router': moduleUrl(`export const useRoute=()=>globalThis.deploymentFixture.route;
    export const useRouter=()=>({replace:value=>Object.assign(globalThis.deploymentFixture.route,{query:value.query})});`),
  '../api/changes': moduleUrl(`import {changeRefresh as merge} from '${changes}';
    export const changeRefresh=callback=>merge(callback,0);
    export const observeChanges=callback=>{globalThis.deploymentFixture.change=callback;return()=>{globalThis.deploymentFixture.change=undefined}};`),
  '../startup': moduleUrl('export const startup={take:()=>undefined}'),
  '../api/deployment': api(['cancelModelJob', 'createPackage', 'getModelJob', 'listModelJobs']),
  '../api/evaluation': api(['cancelEvaluation', 'evaluationLogs', 'getEvaluation', 'listEvaluations']),
  '../types/models': pathToFileURL(require.resolve('../src/types/models.ts')).href,
  '../components/models/ModelReport.vue': moduleUrl('export default {}'),
  '../utils/id': moduleUrl("export const createUuid=()=> 'test-key'"),
}
const compiled = ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext } }).outputText.replace(/from ['"]([^'"]+)['"]/g,
  (_match, name) => `from '${imports[name]}'`)
const page = (await import(moduleUrl(compiled))).default
page.render = () => null

// A Vue renderer without a browser is enough to exercise KeepAlive lifecycle and actual requests.
const renderer = createRenderer({
  createElement: () => ({ children: [] }), createText: text => ({ text }), createComment: () => ({}),
  insert(child, parent) { child.parent = parent; parent.children.push(child) },
  remove(child) { child.parent?.children.splice(child.parent.children.indexOf(child), 1) },
  setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text },
  parentNode: node => node.parent, nextSibling: () => null, patchProp() {},
})
const settle = async () => { await nextTick(); await new Promise(resolve => setTimeout(resolve, 15)); await nextTick() }

function mount() {
  const fixture = { route: reactive({ fullPath: '/deployments', query: {} }), calls: [], change: undefined,
    deferred: undefined,
    call(name, args) {
      this.calls.push({ name, args })
      if (name === 'listModelJobs' && args[0] === 'exports' && this.deferred) return this.deferred
      if (name === 'getModelJob' || name === 'getEvaluation') return Promise.resolve({ id: args[1] ?? args[0], logs: [{ sequence: 1, message: 'already included' }] })
      return Promise.resolve({ items: [], total: 0 })
    } }
  globalThis.deploymentFixture = fixture
  const root = defineComponent({ setup: () => () => h(KeepAlive, null, [h(page)]) })
  const app = renderer.createApp(root)
  app.mount({ children: [] })
  return { fixture, app, actions: app._instance.subTree.component.subTree.component.setupState }
}

test('loads each list once, then refreshes only the topic that changed', async () => {
  const { fixture, app } = mount()
  try {
    await settle()
    assert.deepEqual(fixture.calls.map(call => call.name), ['listModelJobs', 'listModelJobs', 'listEvaluations'])
    fixture.calls.length = 0
    fixture.change({ topic: 'packages', id: 'one' })
    await settle()
    assert.equal(fixture.calls.length, 1)
    assert.equal(fixture.calls[0].args[0], 'deployment-packages')
    fixture.calls.length = 0
    fixture.change({ topic: 'training' })
    await settle()
    assert.equal(fixture.calls.length, 0)
  } finally { app.unmount() }
})

test('export detail uses included logs and unrelated updates do not reload it', async () => {
  const { fixture, app } = mount()
  try {
    await settle(); fixture.calls.length = 0
    fixture.route.query = { tab: 'exports', job: 'export-one' }
    fixture.route.fullPath = '/deployments?job=export-one'
    await settle()
    assert.deepEqual(fixture.calls.map(call => call.name), ['listModelJobs', 'getModelJob'])
    fixture.calls.length = 0
    fixture.change({ topic: 'packages' })
    await settle()
    assert.deepEqual(fixture.calls.map(call => call.name), ['listModelJobs'])
    assert.equal(fixture.calls[0].args[0], 'deployment-packages')
  } finally { app.unmount() }
})

test('reconnect resync reloads all lists and scope disposal removes the subscription', async () => {
  const { fixture, app } = mount()
  await settle(); fixture.calls.length = 0
  fixture.change(null)
  await settle()
  assert.deepEqual(fixture.calls.map(call => call.name), ['listModelJobs', 'listModelJobs', 'listEvaluations'])
  app.unmount()
  assert.equal(fixture.change, undefined)
})

test('retains another change received while the first refresh is in flight', async () => {
  const { fixture, app } = mount()
  try {
    await settle(); fixture.calls.length = 0
    let finish
    fixture.deferred = new Promise(resolve => { finish = resolve })
    fixture.change({ topic: 'exports' })
    await settle()
    fixture.change({ topic: 'exports' })
    fixture.deferred = undefined
    finish({ items: [], total: 0 })
    await settle(); await settle()
    assert.equal(fixture.calls.length, 2)
    assert.ok(fixture.calls.every(call => call.args[0] === 'exports'))
  } finally { app.unmount() }
})

test('manual refresh reloads all lists and independent evaluation still reads its logs', async () => {
  const { fixture, app, actions } = mount()
  try {
    await settle(); fixture.calls.length = 0
    actions.refreshAll()
    await settle()
    assert.deepEqual(fixture.calls.map(call => call.name), ['listModelJobs', 'listModelJobs', 'listEvaluations'])
    fixture.calls.length = 0
    fixture.route.query = { tab: 'reports', job: 'evaluation-one' }
    fixture.route.fullPath = '/deployments?tab=reports&job=evaluation-one'
    await settle()
    assert.deepEqual(fixture.calls.map(call => call.name), ['listEvaluations', 'getEvaluation', 'evaluationLogs'])
  } finally { app.unmount() }
})
