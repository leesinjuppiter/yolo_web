# 检测系统工作台

基于 Vue、FastAPI、PostgreSQL 和 Ultralytics YOLO11 的视觉数据与模型管理工作台，覆盖图片标注、数据集校验、CPU/GPU 训练、模型版本登记、独立评估、ONNX 导出和部署包下载。

业务记录保存在 PostgreSQL；图片、训练快照、权重和导出制品保存在文件系统。当前面向单用户开发测试，训练使用单任务串行队列。

## 功能范围

| 模块 | 当前支持 |
|---|---|
| 数据集 | 检测、分割、旋转框（OBB）、分类；图片与类别管理、标注、负样本、分集、校验、精确重复审核、质量报告 |
| 数据交换 | YOLO/COCO ZIP 或后端本地目录导入；YOLO ZIP 导出，保留已保存的 train/val/test 划分 |
| 训练 | YOLO11 n/s/m/l/x；从零训练、已有权重微调、模型版本复用、冻结层、检查点恢复；CPU 或单张 CUDA GPU |
| 实时监控 | 进度、损失、验证指标、日志、参数、资源采样、预览、训练产物 ZIP 下载 |
| 模型仓库 | 注册版本、来源追溯、元数据编辑、归档/恢复、受引用保护的删除、符合条件的评估对比 |
| 独立评估 | Detect/OBB，使用来源训练快照的 test 分集，当前在 CPU 上执行 |
| 部署中心 | Detect/OBB 的 ONNX FP32 导出、配对验证、CPU 性能测试、部署包生成与下载 |

已有姿态估计数据集可在“全部”视图中打开；当前新建训练任务未开放 Pose。远程 SSH 下发、在线切换、灰度发布、运行监控和回滚尚未实现。

## 环境与依赖

当前开发验证基线如下，不代表其他版本组合均已验证：

| 组件 | 验证基线 |
|---|---|
| 操作系统 | Ubuntu 22.04 x86_64；另有 Windows 本地运行入口 |
| Python | 3.12，使用 Conda 环境 |
| PostgreSQL | 17 |
| Node.js | 24，npm 11 |
| 前端 | Vue 3、TypeScript、Vite、vue-konva，以 `frontend/package-lock.json` 为准 |
| GPU 训练 | RTX 5060 Ti；PyTorch 2.8.0+cu128、torchvision 0.23.0+cu128 |
| 训练框架 | Ultralytics 8.4.115 |
| ONNX 导出与 CPU 验证 | onnx 1.23.2、onnxruntime 1.31.1 |

所有 Python 依赖均安装在 Conda 环境中。以下命令在仓库根目录执行：

```bash
conda create -n vision-platform python=3.12 -y
conda activate vision-platform
python -m pip install -r backend/requirements.txt
```

训练需要另外安装 PyTorch、torchvision 和 Ultralytics。按机器选择下面一种 PyTorch 构建。

CPU 环境：

```bash
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
```

与已验证 GPU 环境一致的 CUDA 12.8 构建：

```bash
python -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
```

安装训练框架；需要 ONNX 导出与部署包时，同时安装导出依赖：

```bash
python -m pip install ultralytics==8.4.115
python -m pip install -r backend/requirements-exports.txt
```

PyTorch 构建应与硬件和驱动匹配，命令参考 [PyTorch 官方历史版本说明](https://pytorch.org/get-started/previous-versions/#v280)。`torch.cuda.is_available()` 还需结合实际 GPU 运算验证。没有 GPU 的电脑可安装 CPU 构建并选择 `cpu`，无需 NVIDIA 驱动。

`backend/requirements.txt` 是后端基础依赖范围，未包含训练框架和完整环境锁定；导出依赖单列在 `backend/requirements-exports.txt`。已有可用环境无需重复安装。

## 配置与启动

### 数据库和环境变量

先创建应用专用 PostgreSQL 数据库和账号。程序不会自动安装 PostgreSQL；迁移只更新表结构。测试需要另建独立数据库。

| 环境变量 | 用途 |
|---|---|
| `WORKBENCH_DATABASE_URL` | 必填，应用 PostgreSQL 连接串，使用 `postgresql+psycopg://...` |
| `WORKBENCH_DATA_DIR` | 图片、快照、报告和制品目录；默认 `backend/data` |
| `WORKBENCH_TRAINING_WEIGHTS_DIR` | 可选，本地预训练权重与官方权重清单目录 |
| `WORKBENCH_TEST_DATABASE_URL` | 后端测试使用的独立 PostgreSQL 数据库 |
| `WORKBENCH_ANALYSIS_WORKER` | 默认启动数据集分析 worker；设为 `0` 可关闭 API 内的分析 worker |
| `WORKBENCH_PUBLIC_CREDENTIALS` | 可选，公网测试网关认证配置 JSON 的路径 |

API、训练、评估和导出进程必须使用相同的应用数据库与数据目录。配置和凭据放在仓库外的受限目录，或已被 Git 忽略的 `.local` 中；连接串中的密码需要 URL 编码。

Linux 示例中的 `CHANGE_ME` 必须替换为实际密码。每个服务终端都需加载相同配置：

```bash
conda activate vision-platform
export WORKBENCH_DATABASE_URL='postgresql+psycopg://workbench:CHANGE_ME@127.0.0.1:5432/inspection_workbench_dev'
export WORKBENCH_DATA_DIR='/hy-tmp/vision-platform-data'
export WORKBENCH_TRAINING_WEIGHTS_DIR='/hy-tmp/vision-platform-weights'
```

代码可以放在 `/hy-tmp/yolo_web`，数据目录可独立设置。恢复数据集与模型需要同时备份 PostgreSQL 和文件目录，仅备份代码不够。

### 通用手动启动

在已激活 Conda 环境、加载上述配置的终端中，从仓库根目录进入 `backend`，先应用迁移：

```bash
cd backend
python -m alembic upgrade head
```

以下服务分别在独立终端或进程托管器中运行，工作目录均为 `backend`：

| 服务 | 启动命令 |
|---|---|
| API 与数据集分析 | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| 训练执行器 | `python -B -m app.training.worker` |
| CPU 独立评估执行器 | `python -B -m app.evaluation.worker` |
| ONNX 导出与部署包执行器 | `python -B -m app.model_exports.worker` |

只启动 API 不会执行训练、独立评估或模型导出队列。服务重启前先确认活动任务状态；浏览器关闭不影响独立执行器继续运行。

另开终端，在 `frontend` 目录启动前端：

```bash
npm ci
npm run dev -- --port 5186
```

打开 [数据集](http://127.0.0.1:5186/#/datasets)、[模型训练](http://127.0.0.1:5186/#/training)、[模型仓库](http://127.0.0.1:5186/#/models) 或 [部署中心](http://127.0.0.1:5186/#/deployments)。Vite 将 `/api` 代理到 `127.0.0.1:8000`。

前端构建和预览：

```bash
npm run build
npm run preview -- --host 127.0.0.1 --port 5186
```

构建命令包含 TypeScript/Vue 类型检查。开发服务和预览服务使用同一端口时，只保留其中一个。

### Windows 现有启动器

`run-backend.ps1` 固定使用名为 `YoloWebAgentStarter` 的 Conda 环境。使用此入口前，需在该环境中安装上述依赖；它不会使用另一个名为 `vision-platform` 的环境。

在仓库根目录的第一个 PowerShell 窗口启动 API：

```powershell
.\run-backend.ps1
```

第二个 PowerShell 窗口启动训练执行器：

```powershell
.\run-backend.ps1 -Mode worker
```

未设置 `WORKBENCH_DATABASE_URL` 时，启动器复用本机 PostgreSQL 17 程序，在 `127.0.0.1:55432` 启动项目独立实例，创建 `inspection_workbench` 库并应用迁移。默认 PostgreSQL 程序目录为 `D:\Program Files\PostgreSQL\17\bin`，可通过 `-PostgresBin` 修改。

数据库、自动生成的凭据和图片默认保存在 `.local`。已有专用数据库可通过当前进程的环境变量指定。评估、导出执行器仍按通用命令启动，并加载相同配置。Windows 前端命令可使用 `npm.cmd`。

### 远程测试访问

内部服务默认监听回环地址。远程开发可使用 SSH 端口转发：

```bash
ssh -N -L 15186:127.0.0.1:5186 -p <SSH端口> <用户名>@<服务器地址>
```

随后打开 `http://127.0.0.1:15186/#/datasets`。SSH 端口、地址和账号按实际实例填写。

恒源云“自定义服务”使用独立认证网关监听 `0.0.0.0:8080`，转发至内部前端和 API。网关还需要 `httpx`，可在项目 Conda 环境中安装。配置、启动与停止方式见 [公网测试入口](docs/公网测试入口.md)。该入口面向单用户测试，尚无多用户角色权限管理；仓库不保存公网账号、SSH 密码或数据库凭据。

## 使用流程

### 数据集与标注

- 新建数据集并添加图片，进入标注页维护类别、绘制并保存标注。“标为负样本”用于人工确认没有目标的图片。
- “调整分集”保存每张图片的 train、val 或 test。导出采用已保存的分集，要求 train、val 各有已标注样本；未标注图片跳过。
- 页面顶部“导入数据集”支持 YOLO/COCO ZIP，ZIP 上传上限为 256 MiB。大数据集可选择后端本地目录，服务会复制图片到项目存储；本地目录指后端所在机器的路径。
- COCO 检测读取 `bbox`；实例分割支持有效多轮廓的连接转换，RLE 和 crowd 掩码仍会拒绝。导入可选择跳过无效图片，并查看原因。
- 数据集卡片中的“导出数据集”打开导出专用弹窗，点击“下载 ZIP”获取 YOLO 归档。可选择是否打包原图、是否包含已标记负样本；分类任务使用分集/类别/图片目录。

“运行校验”“精确重复”“质量报告”显示最近的后台报告，更新时可继续查看上次结果。文件指纹和检查记录会复用；外部替换或删除图片后，可用“重新扫描”复查。

精确重复审核按 SHA-256 分组。人工可确认两张均保留，或明确排除其中一张。排除保留原图、标注与分集，可从“已排除样本”恢复；恢复后重新参与校验、查重和导出。

### YOLO11 权重与训练

四类任务均提供 n、s、m、l、x 五种从零训练结构。已有权重微调仅列出配置目录中真实存在、任务类型匹配的文件：

| 任务 | 权重文件示例 | 官方预训练数据 |
|---|---|---|
| 检测 | `yolo11n.pt` … `yolo11x.pt` | COCO |
| 分割 | `yolo11n-seg.pt` … `yolo11x-seg.pt` | COCO |
| OBB | `yolo11n-obb.pt` … `yolo11x-obb.pt` | DOTAv1 |
| 分类 | `yolo11n-cls.pt` … `yolo11x-cls.pt` | ImageNet |

官方权重接入使用同目录的 `official-yolo11.json` 记录来源与预期哈希；没有官方清单的本地权重标为本地预训练。20 份权重文件未纳入 Git，新机器需单独准备权重、清单和 `WORKBENCH_TRAINING_WEIGHTS_DIR`。来源及验证见 [YOLO11 官方预训练权重](docs/YOLO11官方预训练权重.md)。

新建训练任务支持从零训练、已有权重微调和已注册版本复用，可配置冻结层、数据加载 workers、优化器等参数。CPU 模式关闭 AMP，从零训练不能冻结随机初始化层。

执行器一次处理一个任务。设备以执行器发布的能力和心跳为准，GPU 信息过期或启动复核失败时不会静默切换到 CPU。失败或取消任务满足快照、检查点等条件时，可恢复为新的执行记录，保留原记录和来源关系。

训练概览显示真实 CPU 型号，并按厂商显示 AMD/Intel 小标。实时监控包含任务信息、Epoch、损失、最新验证指标、设备信息，以及日志、曲线、系统监控、参数和文件管理。

- 容器环境优先读取 cgroup v1/v2 内存上限和同一范围的占用，显示“实例内存”；占用包含文件缓存。
- 无有效容器限制时显示宿主机内存。旧任务保留历史宿主机采样，页面标明口径。
- 文件管理统一提供“下载训练产物 ZIP”，包含该任务已登记的产物，下载前核对完整性。
- 每次训练在数据目录 `training/<任务 ID>` 中保留快照、参数、日志和输出。输入快照包含图片副本，需预留相应磁盘空间。

### 模型仓库与独立评估

成功训练后，点击顶部“注册模型版本”并二次确认，登记最优权重、来源任务和数据快照。版本可编辑元数据、归档/恢复，也可用于新的微调任务。

仓库支持四类训练结果；首版独立评估仅支持 Detect/OBB，在 CPU 上使用来源训练快照的 test 分集。缺少 test 分集时不能创建独立评估。未完成独立验证的版本不会被当作已验证模型。

多模型对比仅在任务、类别、样本、标注和评估协议等条件兼容时计算差异；不兼容时展示原因。训练任务页不计算跨数据集平均精度。

模型删除需要二次确认，已有评估、导出或派生训练等引用时禁止删除；可使用归档保留追溯关系。归档后不能创建新的评估、导出、微调或部署包构建。

### ONNX 导出与部署包

Detect/OBB 可创建 ONNX FP32 导出，包括模型与快照校验、ONNX 加载、PyTorch/ONNX 原始输出检查、同一 test 分集配对评估和 CPU 性能测试。

导出成功后，在部署中心生成并下载部署包 ZIP。包内包含模型、类别、输入与预处理配置、清单、报告、依赖记录、校验及推理脚本，具体以包内 README 为准。

1. 在独立目录解压，按包内 README 准备匹配的 Conda 环境与依赖。
2. 执行 `python -B runtime/verify.py` 校验包内容。
3. 按包内说明使用 `runtime/infer.py` 进行文件推理。

部署包不含离线安装 wheel；哈希校验用于完整性检查，不是数字签名。当前部署中心完成到制品生成与下载，尚不执行远程下发或在线切换。详细边界见 [模型仓库与部署包](docs/模型仓库与部署包-实现与验证.md)。

## 检查与测试

前端在 `frontend` 目录执行：

```bash
npm run typecheck
npm run build
```

后端测试需要项目 Conda 环境中的 `pytest`、`httpx` 和独立 PostgreSQL 测试库。Linux 示例，在 `backend` 目录执行：

```bash
python -m pip install pytest httpx
export WORKBENCH_TEST_DATABASE_URL='postgresql+psycopg://workbench:CHANGE_ME@127.0.0.1:5432/inspection_workbench_test'
WORKBENCH_DATABASE_URL="$WORKBENCH_TEST_DATABASE_URL" python -m alembic upgrade head
python -B -m pytest -q
```

测试库需事先创建，不能与开发库相同。未提供测试数据库时，依赖该库的测试会跳过；检查结果应同时查看失败数和跳过数。

已有验证覆盖四类任务短训练、冻结微调、检查点恢复、Detect/OBB CPU 评估与部署包、制品完整性检查，以及页面和资源采样回归。这些检查验证功能与执行链，不证明真实数据准确率、工业吞吐量或生产就绪。现有依赖文件并非完整锁文件，从空环境安装及不同目标硬件仍需单独验收。

## 目录与相关文档

```text
backend/
  app/api/            HTTP API
  app/dataset/        数据集、导入导出、后台分析
  app/training/       训练队列、快照、执行器与资源采样
  app/models/         模型版本、来源与生命周期
  app/evaluation/     独立评估与对比
  app/model_exports/  ONNX 导出与部署包构建
  app/deployment/     部署包服务
  alembic/            数据库迁移
  tests/              后端测试
frontend/
  src/                Vue 页面、标注组件、类型与 API 客户端
docs/                 任务规划、实现说明与阶段验证记录
```

- [服务器开发与验证](docs/服务器开发与验证.md)：早期训练链路与服务器验证记录。
- [YOLO11 官方预训练权重](docs/YOLO11官方预训练权重.md)：来源、命名和校验。
- [模型仓库与部署包](docs/模型仓库与部署包-实现与验证.md)：评估、导出、打包与验证边界。
- [公网测试入口](docs/公网测试入口.md)：临时认证网关和端口转发。

阶段文档保留当时环境、任务 ID 和验证结果；部分历史数据已在后续人工测试前清理，不能将历史任务 ID 视为当前在线记录。当前功能以本 README 和对应代码为准。
