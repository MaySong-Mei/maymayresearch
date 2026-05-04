# research-harness

为自治科研 agent 设计的 thesis 树脚手架。研究本身的过程（提假设 → 设计实验 → 跑 → 修正 thesis → 分支 → 合成）当作一个 git 上的可分支可合并对象来管理，agent 用 CLI 操作它。

* 🐙 GitHub: https://github.com/MaySong-Mei/maymayresearch
* 🌐 示例 dashboard: https://maymayresearch.vercel.app/

---

## 设计原则

1. **git 是 source of truth**。所有 thesis 节点 = git commit。分支 = thesis fork。merge = thesis synthesis。Append-only，diary 不改父节点，只能往后长。
2. **agent 只做 `harness commit`**。同步 / 渲染 / 部署都是 git hook 的副作用，不参与 agent 决策路径。
3. **Reviewer 提建议不否决**。falsifiability、ceiling、"is null" 这些规则只 leave comment，不 block commit —— 信任 agent 的判断。
4. **Vercel 只做静态托管**。研究数据全在本地，公网只见渲染快照，没有写入入口。
5. **可选层都是可选的**。Supabase / Realtime / Edge Function 都可以接，但不是任何 agent 路径的硬依赖。

---

## 快速开始

```bash
git clone https://github.com/MaySong-Mei/maymayresearch.git
cd maymayresearch

# 配置（最少需要 Vercel 那一段才能 deploy）
cp .env.example .env  # 自己填，或直接编辑 .env
# 必填：VERCEL_TOKEN, VERCEL_PROJECT, VERCEL_SCOPE

# 跑测试
python3 -m unittest discover -s tests

# 起一个研究 repo
python3 -m harness.cli --repo ~/research/my_first_idea init
# 自动装 post-commit hook → 之后每次 commit 都会触发 deploy

# 跑完整 demo（生成 7 节点的示例研究 + render HTML）
python3 -m harness.demo /tmp/demo_repo /tmp/demo.html
open /tmp/demo.html
```

---

## 核心概念

### Thesis 节点

每个 commit = 一个 thesis 节点。结构：

| 字段 | 含义 |
|---|---|
| `claim` | 假设本身（一句话） |
| `design` | 实验设计 / 方法论 |
| `prediction` | 可证伪的预测 |
| `evidence` | 实验结果 |
| `decision` | 下一步决策（指向哪个 child branch） |
| `notes` | 注意事项 |
| `review_comments` | reviewer 自动留的 comment |
| `type` | `root` / `narrow` / `rigor` / `reframe` / `pivot` / `synthesis` |
| `status` | `pending` / `supported` / `not-detected` / `refuted` / `ceiling-bound` / `exhausted` |

**重要**：`status` 不能写 `is null` 或 `null hypothesis confirmed` —— reviewer 会吐槽。N=15 时 p=0.51 的正确说法是 `not-detected`，不是 "null"。

### 分支类型

| 类型 | 何时用 | 例 |
|---|---|---|
| `root` | 第一次开题 | "Probes 必要性" |
| `narrow` | 同一 thesis 上继续推进 | "在 QuixBugs 上测一下" |
| `rigor` | 严格化重测（更大 N、更强 baseline） | "v1 的 win 是 artifact 吗？" |
| `reframe` | 重新 frame thesis（旧 claim 不成立，提一个相关但不同的） | "probe selection 不对，rep update 才是" |
| `pivot` | 完全换 domain / 换 task | "code 域跑完了，去 OOD 函数拟合" |
| `synthesis` | 合并两条 branch 成新 claim（git merge commit） | "code-tied + rep-update-tied = boundary thesis" |

### 工作流（agent 视角）

```
  1. harness context              ← 看现在在哪、附近 branch 试过啥
  2. 决策：narrow / branch / synthesize / stop
  3. harness commit / branch / synthesize
  4. 读 review_comments，决定回应或忽略
  5. (post-commit hook 自动 deploy)
  6. 回 1
```

---

## CLI 参考

```bash
# 仓库管理
harness --repo <path> init [--no-hook] [--hook-target {auto,vercel,supabase}]
harness --repo <path> install-hook [--hook-target {vercel,supabase}]
harness --repo <path> context        # JSON 输出：当前 branch / 最近 ancestors / 兄弟 branch 状态 / diary tail
harness --repo <path> list           # 所有节点 + 分支

# 编辑节点
harness --repo <path> commit \
  --type {root,narrow,rigor,reframe,pivot} \
  --status {pending,supported,not-detected,refuted,ceiling-bound,exhausted} \
  --claim "..." \
  --design "..." \
  --prediction "..." \
  --evidence "..." \
  --decision "..." \
  --notes "..." \
  --diary "## 这一段会 append 到 FINDINGS.md"

# 大段文本通过 stdin
echo '{"node": {...}, "diary": "..."}' | harness --repo <path> commit --from-json -

# 分支 / 切换
harness --repo <path> branch --name rigor-1 [--from-ref HEAD]
harness --repo <path> checkout main

# 合成
harness --repo <path> synthesize \
  --new-branch synth-1 \
  --base rigor-1 --other reframe-1 \
  --type synthesis --status supported \
  --claim "..." --evidence "..."

# Reviewer
harness --repo <path> review            # 重跑 reviewer 在 HEAD 节点上

# 部署 / 渲染
harness --repo <path> render --out tree.html
harness --repo <path> deploy [--project ...] [--scope ...]   # 走 Vercel
harness --repo <path> publish           # 走 Supabase（可选）
harness --repo <path> serve             # 本地 HTTP（git 轮询版）
```

---

## Dashboard

* 横向树状图：时间从左到右，颜色编码 branching type，徽章编码 status
* **点节点圆圈** → modal 显示完整 6 段（设计 / 预测 / 结果 / 决策 / 审阅 / 备注）
* **顶栏"日记"按钮** → 完整 FINDINGS.md（h1/h2/h3、bold、code 都解析）
* URL 参数：`?focus=<short>` 直接打开某节点，`?diary=1` 直接打开日记
* 默认 30 秒自动刷新

部署目标默认是 Vercel（静态托管，无 backend）。post-commit hook 自动调用 `harness deploy`，每次 commit 后 ~18 秒生效。

```bash
# 手动 deploy（debug 用）
python3 -m harness.cli --repo <repo> deploy
```

---

## 配置

`.env`（在 `harness/` 下，已 gitignore）：

```
# 必填：Vercel 部署
VERCEL_TOKEN=vcp_...
VERCEL_PROJECT=maymayresearch        # 或你的项目名
VERCEL_SCOPE=...                      # team scope

# 可选：Supabase 数据镜像 + Realtime
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_PROJECT_REF=xxx
SUPABASE_ANON_KEY=sb_publishable_...
SUPABASE_SERVICE_ROLE_KEY=sb_secret_...
SUPABASE_DB_PASSWORD=...
SUPABASE_ACCESS_TOKEN=sbp_...         # 仅用于部署 Edge Function
```

`harness init` 检测：

* 设了 `VERCEL_TOKEN` → hook 默认指向 Vercel deploy
* 没设 Vercel 但设了 `SUPABASE_URL` → hook 指向 Supabase publish
* 都没设 → 不装 hook

---

## Reviewer 规则

非阻塞，只 leave comment。当前规则：

| 规则 | 触发 |
|---|---|
| `[falsifiability]` | non-root 节点缺 prediction |
| `[phrasing]` | claim/evidence 出现 "is null"、"null hypothesis confirmed"、"thesis is false" 等 overclaim |
| `[ceiling]` | claim 含方向性词（helps / outperforms / doesn't help），但全文没提及 ceiling / saturation / headroom |
| `[reframe]` | type=reframe 的节点没指出哪个 prior claim 失效及为何 |

后续可换成 LLM-based reviewer，接口不变（输入 ThesisNode → 输出 List[str]）。

---

## 测试

```bash
python3 -m unittest discover -s tests
# 49 tests:
#  - core ops (git, branch, merge, commit)
#  - reviewer rules
#  - SVG layout
#  - HTML render
#  - CLI subcommands (subprocess)
#  - server endpoints (HTTP fetch)
#  - publisher (mocked HTTP)
#  - deploy (mocked subprocess)
#  - hook installation
#  - Supabase 集成测试（需要 .env，无 .env 自动跳过）
```

---

## 文件布局

```
harness/
├── core.py                  # ThesisNode + ResearchRepo (git 包装)
├── reviewer.py              # 非阻塞 review
├── render.py                # 静态 HTML 渲染
├── server.py                # 本地 HTTP dashboard（fallback，git poll）
├── publisher.py             # Supabase 镜像（可选）
├── cli.py                   # 命令行入口
├── demo.py                  # Python API demo（小型）
├── agent_demo.py            # CLI 驱动的 demo（仿真 agent）
├── dashboard.html           # Realtime dashboard 模板（用 Supabase 时用）
├── migrations/              # Supabase schema migrations
└── tests/                   # 49 测试
```

---

## 路线图（非承诺）

* `--async` hook：commit 立即返回，deploy 后台跑
* 多 repo dashboard：同一 vercel project 路径分发多个研究的快照
* LLM-based reviewer：用模型替代正则
* Agent loop driver：把 Claude Code session 真正接上去跑一个研究

---

## 名字说明

`maymayresearch` 是这个仓库的名字，不是工具的名字。工具叫 `research-harness`，可以放在任何 vercel project 下。
