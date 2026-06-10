# 部署手册：把程序放到云端，发链接给朋友用

目标：朋友打开一个网址 → 输入暗号 → 各自管理自己的自选股。全程免费。

整个过程分 4 步，照着做即可。遇到任何一步卡住，截图发我。

---

## 第 1 步：建数据库（Supabase，存自选股）

1. 打开 [supabase.com](https://supabase.com) → 用 GitHub 账号登录 → New project
   （名字随便起，数据库密码记一下，地区选离你近的）
2. 项目建好后，左侧点 **SQL Editor** → New query，粘贴下面**框内的纯 SQL**
   （⚠️ 不要把代码框的反引号 ``` 复制进去，只从 `create` 复制到 `;`），点 **Run**：

   ```sql
   create table watchlists (
     "user" text primary key,
     items jsonb default '[]'::jsonb
   );
   ```

   看到 "Success. No rows returned" 就建好了。

3. 左侧 **Project Settings → API**，记下两个值（下面第 3 步要用）：
   - **Project URL**（形如 `https://xxxx.supabase.co`）
   - **anon public** 的 key（很长一串）

---

## 第 2 步：把代码传到 GitHub

在项目目录下打开终端，依次执行（`<你的仓库地址>` 换成你新建的 GitHub 仓库）：

```bash
cd ~/Desktop/claude/project-f/股票分析程序
git init
git add .
git commit -m "股票分析助手"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

> `.gitignore` 已经帮你排除了密钥和本地数据（`.ai_config.json`、`watchlist.json`、
> `secrets.toml`），不会泄露。

---

## 第 3 步：部署到 Streamlit Cloud

1. 打开 [share.streamlit.io](https://share.streamlit.io) → 用 GitHub 登录
2. **New app** → 选你刚传的仓库 → Main file 填 `app.py` → Deploy
3. 部署后，进 **App 右下角 ⋮ → Settings → Secrets**，把下面内容填好粘进去（保存）：

   ```toml
   APP_PASSCODE = "你们的暗号"
   SUPABASE_URL = "第1步记的 Project URL"
   SUPABASE_KEY = "第1步记的 anon public key"
   ```

4. 保存后 App 会自动重启。打开网址，应该先要你输暗号 + 名字。

---

## 第 4 步：发给朋友

把网址 + 暗号发给朋友即可。每人进来填自己的名字，各看各的自选股，数据存在
Supabase 不会丢。

---

## ⚠️ 可能遇到的问题

**数据拉不出来 / 很慢？**
程序的数据源（东方财富）是国内站，而 Streamlit Cloud 服务器在国外，跨境访问
可能慢或偶尔失败。如果普遍拉不到，告诉我，我帮你换数据源或换个能连国内的部署方式。

**想限制只有特定人能开？**
Streamlit Cloud 的 App Settings 里可以设成 Private 并按邮箱白名单授权（进阶，需要时再说）。

**改了代码怎么更新线上？**
本地改完，重新 `git add . && git commit -m "更新" && git push`，Streamlit Cloud 会自动重新部署。
