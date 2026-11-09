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
- 数据集交换支持真正的 YOLO ZIP 导入和下载。导出采用归一化标签，分类任务采用分集／类别目录。未标注图片不会进入训练归档。
- 旧版 IndexedDB 数据留在原来的浏览器站点中。新版本使用独立的后端数据源。
