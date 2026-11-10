# 检测系统工作台

检测系统工作台使用 Vue、FastAPI 和 PostgreSQL 管理视觉训练数据。标注和类别等记录保存在 PostgreSQL，图片存入本地文件系统。前端支持目标检测、实例分割、旋转框、姿态估计和图像分类。

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
- 「运行校验」和「质量报告」读取数据库中的实际记录。可从附有图片的问题跳到对应样本。
- 数据集交换支持 YOLO ZIP 导入和下载，浏览器上传的 ZIP 最大为 256 MiB。大数据集可在导入来源中选择「本地 YOLO 目录」，浏览或粘贴后端所在机器的绝对目录。服务会复制图片到项目存储，并导入所选目录内的类别、分集和标签。目录导入无需上传或打包 ZIP。
- COCO 可通过 ZIP（同样限制 256 MiB）或「本地 COCO 目录」导入。根目录需同时包含 COCO JSON 和图片，支持 `annotations/instances_train2017.json` 配合 `train2017/`，或 `train/_annotations.coco.json`、`valid/_annotations.coco.json` 等布局。分集可从目录或 JSON 文件名识别，无法识别的图片保留为待分配。检测读取 `bbox`，实例分割要求每个对象有一个多边形轮廓。分割导入会拒绝 RLE、crowd 和多轮廓实例。
- 导出采用归一化标签，分类任务采用分集／类别目录。未标注图片不会进入训练归档。
- 旧版 IndexedDB 数据留在原来的浏览器站点中。新版本使用独立的后端数据源。
