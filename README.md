# DLsite 小工具 🛠️

> **批量处理 DLsite 游戏文件夹的 GUI 工具**  
> 版本 **v2.4** | 仅 Windows

![Python](https://img.shields.io/badge/Python-3.7%2B-3776AB)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)

---

## 三大功能

| 功能 | 说明 |
|------|------|
| **★ 一键处理** | 改名 + 抓封面设图标，一步到位 |
| **封面图标** | 单独下载封面 → 生成 ICO → 设文件夹图标 |
| **重命名** | 按 RJ号/社团名/作品名等格式批量改名 |

## 快速开始

### 前置条件

- Python 3.7+
- 依赖包：

```
pip install requests pillow pyquery
```

### 启动

```bat
# 方式一：双击 launch.bat
# 方式二：命令行
python dlsite_tools.pyw
```

### 使用流程

1. 顶部**选择或输入目标目录**，点击「重新扫描」
2. 三个标签页分别对应三大功能，选一个执行
3. 可选**普通模式**（跳过已完成的）或**重做模式**（全部重新处理）

---

## 重命名格式设置

点击格式标签旁的 **「...」** 按钮打开设置对话框：

| 选项 | 内容 |
|------|------|
| **字段** | RJ号 / 社团名 / 作品名 / 发售日期 / 年龄限制 / 作品形式 |
| **括号** | `[]`方括号 / `()`圆括号 / `【】`书名号 / 无括号 |
| **分隔符** | 空格 / `_`下划线 / `-`横线 / 无分隔 |
| **图标背景** | 取色填充 / 白色 / 透明 |
| **预设** | 默认（`[RJ号][社团名]作品名`）/ 带日期 |

预览会实时更新。

## 包裹模式

勾选顶部「包裹模式」后：

- **不改原文件夹名**，在外层创建一个格式化后的父文件夹
- 原文件夹内容不动（同盘移动，零开销）
- 封面图标挂在**父文件夹**上
- 适用于不想动原始文件夹名的场景

## 代理设置

如需代理，设置环境变量 `DLISTE_PROXY`：

```bat
set DLISTE_PROXY=http://127.0.0.1:7890
```

可在 `launch.bat` 中加一行再启动。

## ⚠️ 注意事项

- 每个文件夹名必须包含 **RJ、VJ 或 BJ 编号**（有无方括号均可）
- 自动间隔 **3 秒**防限流（DLsite 有反爬机制）
- 封面图标操作会产生 `desktop.ini` 和 `@folder-icon-xxx.ico` 文件
- 恢复默认图标可一键移除自定义图标和 `desktop.ini`

## 项目结构

```
dlsite_tools/
├── dlsite_tools.pyw    # 主程序
├── launch.bat          # 启动脚本
├── README.md           # 本文件
├── .gitignore
```

## 免责声明

本工具由 AI 辅助生成，**仅供个人学习参考**。  
使用前请充分测试，作者不对任何直接或间接损失承担责任。  
本工具**完全免费**，任何收费行为均为诈骗。

## 致谢

封面抓取逻辑参考了 [yodhcn/dlsite-doujin-renamer](https://github.com/yodhcn/dlsite-doujin-renamer)（功能更全、社区活跃，推荐了解）。  
本工具为独立开发，与原项目无任何关系。
