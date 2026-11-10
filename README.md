# 检测系统工作台

检测系统工作台使用 Vue、FastAPI 和 PostgreSQL 管理视觉训练数据。标注和类别等记录保存在 PostgreSQL，图片存入本地文件系统。前端可选任务类型包括目标检测、实例分割、旋转框和图像分类。已有姿态估计数据集可在「全部」视图中打开。

## 在 Windows 上运行

第一个 PowerShell 窗口启动后端。启动器复用本机 PostgreSQL 17 的程序，在 `127.0.0.1:55432` 启动项目独立实例，创建 `inspection_workbench` 库并应用迁移。

```powershell
Set-Location 'C:\Users\13480\Desktop\codex_\PythonProject'
.\run-backend.ps1
```

启动器使用 `YoloWebAgentStarter` 环境。默认的 PostgreSQL 程序目录为 `D:\Program Files\PostgreSQL\17\bin`，如有变化可传入 `-PostgresBin`。数据库、凭据及图片默认位于项目的 `.local`，由 Git 忽略。已有专用库可以通过当前进程的 `WORKBENCH_DATABASE_URL` 指定（`postgresql+psycopg://…`）。`WORKBENCH_DATA_DIR` 可指定图片目录。

第二个 PowerShell 窗口启动前端：

```powershell
Set-Location 'C:\Users\13480\Desktop\codex_\PythonProject\frontend'
npm.cmd ci
npm.cmd run dev -- --port 5186
```

打开 [工作台](http://127.0.0.1:5186/#/datasets)。Vite 将 `/api` 请求代理到 `127.0.0.1:8000`。该项目在 Node.js 24 与 npm 11 上开发。

```powershell
npm.cmd run build
```

## 数据集流程

- 数据集首页支持列表与卡片切换、搜索、任务筛选、分页和统计。
- 新建数据集后上传图片，进入标注页新增类别、绘制、编辑并保存。通过「标为负样本」记录已人工确认无目标的图片。
- 「调整分集」支持设置每张图片的 train、val 或 test。导出使用已保存的分集，并要求 train、val 分别有已标注样本。
- 「运行校验」「精确重复」「质量报告」显示 PostgreSQL 中最近生成的报告。后台更新时可继续查看上次结果，问题明细支持跳到相关图片。
- 数据集交换支持 YOLO ZIP 导入和下载，浏览器上传的 ZIP 最大为 256 MiB。大数据集可在导入来源中选择「本地 YOLO 目录」，浏览或粘贴后端所在机器的绝对目录。服务会复制图片到项目存储，并导入所选目录内的类别、分集和标签。目录导入无需上传或打包 ZIP。
- COCO 可通过 ZIP（同样限制 256 MiB）或「本地 COCO 目录」导入。根目录需同时包含 COCO JSON 和图片，支持 `annotations/instances_train2017.json` 配合 `train2017/`，或 `train/_annotations.coco.json`、`valid/_annotations.coco.json` 等布局。分集可从目录或 JSON 文件名识别，无法识别的图片保留为待分配。检测读取 `bbox`。实例分割支持多轮廓，同一实例的有效轮廓通过往返线连接为一个可导出至 YOLO 的多边形。RLE 和 crowd 掩码仍会被拒绝。
- 导出采用归一化标签，分类任务采用分集／类别目录。未标注图片不会进入训练归档。
- 旧版 IndexedDB 数据留在原来的浏览器站点中。新版本使用独立的后端数据源。

## 后台数据集分析

启动后端时会启动一个分析 worker。导入和修改数据时，数据写入与报告任务登记在同一个事务中。连续编辑会合并到同一报告的待办任务，后端重启后可继续处理。迁移会给已有图片的数据集排队生成首份报告。

逐图文件签名、尺寸、可读状态和哈希保存在 PostgreSQL。报告刷新时复用文件签名相符的检查记录。外部替换或删除工作台图片后，可从校验或查重报告点「重新扫描」来检查文件变化。质量报告的「重新统计」会刷新标注和类别汇总。

`GET /api/datasets/{id}/reports/{kind}/snapshot` 读取报告与任务状态。`POST /api/datasets/{id}/reports/{kind}/refresh` 可请求后台刷新，设置 `force` 为 `true` 可手动重算。需要只启动 API 时，可以给该进程设置 `WORKBENCH_ANALYSIS_WORKER=0`。

## 精确重复人工审核

打开「精确重复」并选择「人工审核」，可并排核对两张原图和它们的分集、尺寸及标注状态。查重按文件 SHA-256 分组。选择「两张都保留」会把该配对归入「已确认重复」。审核结论绑定两张图片的内容指纹，替换图片后可重新产生待审配对。

选择丢弃一张时，需要明确选中要排除的样本。排除会将该图移出有效数据集并更新报告，原图、分集和标注保留在「已排除样本」中，可以从那里恢复。恢复后的样本会重新参与查重、校验和导出。
