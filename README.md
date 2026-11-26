<a id="readme-top"></a>

<div align="center">

<h1>ariel-claude-backup</h1>

<p><strong>换 Claude 账号、换电脑，对话不丢、文件夹不乱的 AI 插件</strong><br>
它每 10 分钟悄悄把你 Claude 里的工作备份到你自己的 GitHub 私有仓库。换号那天说一句话，以前的对话全回来，点进去接着聊。</p>

<p>
<img alt="版本" src="https://img.shields.io/badge/version-1.0.5-blue?style=flat-square">
<img alt="Claude" src="https://img.shields.io/badge/Claude-桌面%20app%20Code%20页-D97757?style=flat-square">
<img alt="macOS" src="https://img.shields.io/badge/系统-macOS-000000?style=flat-square">
<img alt="License" src="https://img.shields.io/github/license/nini818726/ariel-claude-backup?style=flat-square">
<img alt="Stars" src="https://img.shields.io/github/stars/nini818726/ariel-claude-backup?style=flat-square">
</p>

<p>
<a href="#快速开始">快速开始</a> ·
<a href="#它是怎么工作的">工作流程</a> ·
<a href="#常见问题">常见问题</a> ·
<a href="https://github.com/nini818726/ariel-claude-backup/issues">反馈问题</a>
</p>

</div>

---

> **一句话装好：** 复制下面这句话，发给 Claude 桌面 app 的 Code 页就行。
>
> ```
> 帮我装上这个：https://github.com/nini818726/ariel-claude-backup
> ```
>
> 装好后它会帮你开始备份。以后作者每次更新，你那边自动变成最新版。

<details>
<summary><strong>目录</strong></summary>

1. [这是什么](#这是什么)
2. [它能做到什么](#它能做到什么)
3. [快速开始](#快速开始)
4. [怎么用](#怎么用)
5. [它是怎么工作的](#它是怎么工作的)
6. [文件夹身份证](#文件夹身份证)
7. [隐私和安全](#隐私和安全)
8. [自动更新](#自动更新)
9. [常见问题](#常见问题)
10. [路线图](#路线图)
11. [参与贡献](#参与贡献)
12. [许可证](#许可证)
13. [致谢](#致谢)

</details>

## 这是什么

Claude 的对话是**跟账号绑在一起**的。换一个账号，左边的对话列表就空了；以前调好的偏好、skill、插件也得重来一遍。

这个插件帮你把这些东西**自动备份到你自己的 GitHub 私有仓库**（只有你能看到）。换号或换电脑时，对 Claude 说一句「从 GitHub 恢复我的 Claude」，以前的对话就全回来，点进去还能接着聊。

- **插件是什么**：装进 Claude 里的一个小工具包。这个插件里有一份写给 AI 的工作说明书（skill）、一个备份程序，和输入框下面的一行状态显示。
- **GitHub 私有仓库是什么**：GitHub 上一个只有你自己能打开的文件夹，免费，专门用来存东西。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 它能做到什么

| | |
|---|---|
| ☁️ **自动备份** | 每 10 分钟一次，只传改过的部分，通常几秒钟就完。不花 Claude 的 token，也不占你电脑空间 |
| 🔁 **一句话恢复** | 换号、换电脑后说一句话，Code 页的对话、记忆、偏好、skill、插件、设置、MCP 配置全部回来，能接着聊 |
| 🕶️ **新账号认不出旧账号** | 上传前自动抹掉旧账号的身份信息，自己检查一遍，**查到一点残留就不传** |
| 📁 **文件夹身份证** | 项目文件夹挪位置、改名字、放进移动硬盘，对话都能自动找到它 |
| 👀 **底部状态行** | 输入框下面一行小字：`☁️ 备份正常 · 18:04 同步过 · 277 个对话`。出问题会变色提醒 |
| 🛡️ **防止误覆盖** | 刚登录的新账号对话很少时，它不会拿空的去覆盖你的备份 |
| 🗓️ **尊重官方规则** | Claude 官方「30 天自动清理旧对话」的规则照常保留，不去改 |

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 快速开始

### 支持哪些软件

| 软件 | 支持 |
|---|---|
| Claude 桌面 app（Mac）的 Code 页 | ✅ |
| Claude Code 命令行（Mac） | ✅ 能备份和恢复对话；侧边栏是桌面 app 的东西 |
| Claude 网页版 / Cowork | ❌ 对话存在官方服务器上，本地拿不到 |
| Windows / Linux | ❌ 暂不支持 |

### 你需要准备什么

- 一个 **GitHub 账号**（免费，没有就去 github.com 注册一个）
- 其他工具不用自己装，AI 会帮你检查并装好：
  - **git**：上传、下载备份用
  - **gh**：GitHub 官方的小工具，用来自动建私有仓库
  - **python3**：运行备份程序（Mac 自带）

### 安装

**方法一（推荐）：交给 AI**

把这句话发给 Claude 桌面 app 的 Code 页：

```
帮我装上这个：https://github.com/nini818726/ariel-claude-backup
```

AI 会照仓库里的 [INSTALL.md](INSTALL.md) 一口气装好，然后直接开始第一次备份。

需要你本人点的只有这几种情况，都是电脑出于安全必须你确认的：
- Mac 第一次装 git 会弹窗，点「安装」
- 装 Homebrew（Mac 上装软件的工具）要输一次开机密码
- 登录 GitHub：浏览器会打开一个确认页面，你点一下「授权」。**密码只由你自己输入**，AI 不会碰

**方法二：自己装**

<details>
<summary>展开看命令</summary>

在 Code 页依次输入：

```
/plugin marketplace add nini818726/ariel-claude-backup
/plugin install ariel-claude-backup@ariel-claude-backup
```

装完打开自动更新：`/plugin` → Marketplaces → 选 ariel-claude-backup → Enable auto-update（第三方插件市场默认是关的）。

然后对 Claude 说「开始备份」。

</details>

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 怎么用

装好以后你几乎什么都不用做。平时会用到的只有这几句话：

| 你想做什么 | 对 Claude 说 |
|---|---|
| 第一次开始备份 | 「开始备份」 |
| 马上手动备份一次 | 「备份」 |
| 换号或换电脑后恢复 | 「从 GitHub 恢复我的 Claude」 |
| 挪了文件夹，不想等 10 分钟 | 「帮我重新对一下对话的文件夹」 |
| 看备份情况 | 看输入框下面那行字就行，或者问「备份状态怎么样」 |

**换号 / 换电脑的完整步骤：**

1. 换电脑的话，先用 U 盘把项目文件夹**整个**拷过去（隐藏的身份证会跟着走）
2. 登录新的 Claude 账号，在 Code 页随便发一句话
3. 按上面的方法装好插件
4. 说「从 GitHub 恢复我的 Claude」
5. 按提示 ⌘Q 退出 Claude 再打开，以前的对话就在左边了

你的 GitHub 上会多出一个私有仓库 `claude-backup`，长这样：

```
claude-home/          对话记录、记忆、skills、设置（已抹掉账号信息）
desktop/              Code 页左边侧边栏的条目
claude.json           MCP 配置、项目列表
folder-ids.json       文件夹身份证名单
pack-manifest.json    这次备份了什么
tool/                 备份程序自己也存一份，新电脑没装插件也能恢复
```

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 它是怎么工作的

| 步骤 | 你做什么 | AI / 程序在后台做什么 |
|---|---|---|
| 1. 安装 | 发一句话，必要时点一下授权 | 装好 git、gh，在你的 GitHub 上建私有仓库 |
| 2. 第一次备份 | 什么都不用做 | 打包对话和设置，抹掉账号信息，自检后上传 |
| 3. 平时 | 照常工作 | 每 10 分钟只传改过的部分，状态写在输入框下面 |
| 4. 挪文件夹 | 照常挪、照常改名 | 按身份证找到新位置，把对话指过去，提醒你重开 |
| 5. 换号 / 换电脑 | 说一句「从 GitHub 恢复我的 Claude」 | 拉下备份，把旧账号原始数据挪到一边存档，把对话放进新账号 |
| 6. 重开 Claude | ⌘Q 再打开 | 新账号接着每 10 分钟备份 |

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 文件夹身份证

Claude 是靠文件夹的**完整路径**记住「这个对话在哪个文件夹里做」的。文件夹一挪位置或改名，对话就找不到地方了。

这个插件会在每个项目文件夹里放一个隐藏小文件 `.claude-folder-id`，里面只有一串随机编号，就像身份证：

- **挪位置、改名字、放进移动硬盘**：每次备份时检查一遍，发现文件夹「搬家」了，就把对应的对话改指到新地址
- **一个对话用了好几个文件夹**：每个文件夹都有自己的身份证，各找各的
- **复制了一份文件夹**：同一张身份证出现在两个地方时，它不会乱猜，只记一条提示
- **git 项目**：自动把身份证加进忽略名单，不会被你提交上去
- **新电脑**：恢复时也按身份证找文件夹，文件夹放在哪都能对上

> 隐藏小文件平时看不到，请别删它。用 U 盘拷文件夹时要拷**整个文件夹**，身份证才会跟着走。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 隐私和安全

- **备份只放在你自己的 GitHub 私有仓库**：别人装了这个插件，备份也是进他自己的仓库，谁也看不到谁的。仓库如果被改成公开，程序会**拒绝上传**。
- **上传前抹掉旧账号信息**：账号编号、组织编号（包括只写前 8 位的写法）、登录邮箱、设备编号、服务器请求编号、AI 思考过程的签名、指向账号内容的 claude.ai 链接、各种密钥。
- **自检通过才上传**：每次上传前再扫一遍，找到一点残留就停下，不上传。
- **你的信息照常保留**：你的偏好、记忆、skill 都是你的，会原样备份，只抹掉「旧 Claude 账号是谁」的信息。
- **不碰你的项目文件**：桌面上的项目文件夹内容不备份（请自己用 U 盘或别的方式保存），插件只往里放一张身份证。
- **要如实说的一点**：抹掉的是你电脑文件里的账号信息。同一台电脑、同一个网络，官方服务器那边仍可能把两个账号联系起来。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 自动更新

| 你在用什么 | 怎么更新 |
|---|---|
| Claude 桌面 app / Claude Code | 安装时打开自动更新（用「交给 AI」的方式装，AI 会提醒你打开），下次开新对话就是新版 |

备份程序在你电脑上有一份固定副本（`~/.claude-backup/bin/`），保证定时备份不会因为更新而断掉。插件更新后，AI 下次帮你操作时会顺手把副本换成新版。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 常见问题

<details>
<summary><strong>备份会不会越来越占硬盘？</strong></summary>

不会一直涨。备份程序每天自动整理一次：本机只留最近约 150 个版本（大约一天），更早的全在 GitHub 上，一个不少；剩下的压缩打包。本机一般占 3G 左右，大头是你所有对话的一份副本。

</details>

<details>
<summary><strong>状态行显示「⚠️ N 个未备份（太大，等你决定）」是什么意思？</strong></summary>

GitHub 不收超过 100 MB 的文件，有的对话（比如做视频、带很多截图的）会超过。备份不会悄悄跳过它们：先不上传，在状态行提醒你，其他对话照常备份。

新开一个对话，截图发给 Claude，或者说「处理未备份的」。Claude 会列出每个是什么对话、多大，你逐个选：

- **压缩上传**：压小了传上去，太大就切块，恢复时自动拼回原样
- **不上传**：电脑上照样留着，只是不传 GitHub，以后不再提醒
- **删掉**：移到废纸篓，能拿回来

A 号、B 号共用同一份备份，选一次两边都算数。

</details>

<details>
<summary><strong>会花我的 Claude token 吗？</strong></summary>

不会。定时备份是你电脑上的一个小程序在跑，不经过 Claude。只有你对 Claude 说话让它帮你操作时，才算一次普通对话。

</details>

<details>
<summary><strong>占我电脑空间吗？</strong></summary>

几乎不占。备份存在 GitHub 上；你电脑上只有一份用来对比改动的本地副本。

</details>

<details>
<summary><strong>每 10 分钟上传一次，会不会很慢、很占网？</strong></summary>

不会。只传这 10 分钟里改过的对话，通常几秒钟就完。第一次备份会久一点。

</details>

<details>
<summary><strong>Cowork 里的对话能带走吗？</strong></summary>

不能。Cowork 和网页版的对话存在官方服务器上，本地拿不到。能带走的是 Code 页的对话和你所有的设置、skill、插件。

</details>

<details>
<summary><strong>连接器（比如 Gmail、Notion）要重新登录吗？</strong></summary>

要。连接器是跟账号授权绑定的，换号以后需要重新点一下授权。MCP 配置本身会恢复。

</details>

<details>
<summary><strong>很久以前的对话也会备份吗？</strong></summary>

会备份你电脑上现有的全部对话。Claude 官方会自动清理 30 天没用过的旧对话，这个插件尊重这个规则，不去改它。

</details>

<details>
<summary><strong>底部那行字显示「⚠️ 上传失败」怎么办？</strong></summary>

多半是网络连不上 GitHub。不用管，10 分钟后会自动重试。一直失败的话，对 Claude 说「备份」，它会告诉你原因。

</details>

<details>
<summary><strong>Windows 能用吗？</strong></summary>

暂时不行，目前只支持 Mac 上的 Claude 桌面 app。

</details>

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 路线图

- [x] 每 10 分钟增量备份到 GitHub 私有仓库
- [x] 抹掉旧账号信息 + 上传前自检
- [x] 换号 / 换电脑一句话恢复，能接着聊
- [x] 文件夹身份证：挪位置、改名、移动硬盘都不乱
- [x] 输入框下面的备份状态行
- [ ] 在全新电脑上从安装到恢复的完整实测
- [ ] Windows 支持

想要什么功能，欢迎到 [Issues](https://github.com/nini818726/ariel-claude-backup/issues) 提。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 参与贡献

欢迎提建议、报问题、改代码：

1. 到 [Issues](https://github.com/nini818726/ariel-claude-backup/issues) 说说你遇到的问题或想法
2. 想直接改：Fork 这个仓库 → 新建分支 → 改好后提 Pull Request（合并申请）

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 许可证

本仓库用 [MIT 许可证](LICENSE)：可以随便用、改、商用，保留作者署名就行。

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>

## 致谢

- [GitHub CLI](https://github.com/cli/cli)（MIT）：自动建私有仓库、登录 GitHub
- [Git](https://git-scm.com/)（GPL-2.0）：增量上传和下载
- 本 README 的结构参考了 [Best-README-Template](https://github.com/othneildrew/Best-README-Template)、[standard-readme](https://github.com/RichardLitt/standard-readme) 和 [Art of README](https://github.com/hackergrrl/art-of-readme)

<p align="right">(<a href="#readme-top">回到顶部</a>)</p>
