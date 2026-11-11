import { listDatasets } from '../api/datasets'
import { listTraining } from '../api/training'
import { listModels } from '../api/models'
import { listModelJobs } from '../api/deployment'
import { listEvaluations } from '../api/evaluation'
import type { JobList } from '../types/models'
import type { Change } from '../api/changes'
import { PagePreloader } from './preloader'
import type { ModuleKey } from './preloader'

export type DeploymentPage = [JobList, JobList, JobList]
export const startup = new PagePreloader([
  { key: 'datasets', label: '数据集', load: async signal => {
    const [, value] = await Promise.all([import('../DatasetsView.vue'), listDatasets(signal)])
    return value
  } },
  { key: 'training', label: '模型训练', load: async signal => {
    const [, value] = await Promise.all([import('../pages/TrainingView.vue'), listTraining({
      status: 'all', task: 'all', architecture: 'all', query: '', sort: 'newest', page: 1, pageSize: 6,
    }, signal)])
    return value
  } },
  { key: 'models', label: '模型仓库', load: async signal => {
    const [, value] = await Promise.all([import('../pages/ModelRegistryView.vue'),
      listModels(new URLSearchParams({ query: '', page: '1', page_size: '10' }), signal)])
    return value
  } },
  { key: 'deployments', label: '部署中心', load: async signal => {
    const [, a, b, c] = await Promise.all([import('../pages/DeploymentCenterView.vue'),
      listModelJobs('exports', signal), listModelJobs('deployment-packages', signal), listEvaluations(signal)])
    return [a, b, c] satisfies DeploymentPage
  } },
])

// Invalidating an unused startup seed does not change any module's automatic update mechanism.
export function invalidateStartup(change: Change | null) {
  const keys: Record<string, ModuleKey[]> = {
    datasets: ['datasets', 'training', 'models'], training: ['training'], worker: ['training'],
    models: ['models', 'training'], evaluations: ['models', 'deployments'],
    exports: ['deployments'], packages: ['deployments'],
  }
  if (!change) startup.invalidate(['datasets', 'training', 'models', 'deployments'])
  else if (change.table !== 'training_logs' && change.table !== 'training_metrics') startup.invalidate(keys[change.topic] ?? [])
}
