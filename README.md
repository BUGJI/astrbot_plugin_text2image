# astrbot_plugin_text2image

将文本渲染为图片的 AstrBot 插件，使用 Playwright Chromium 渲染。

## 安装

```bash
pip install playwright
playwright install chromium
```

将插件文件夹放入 AstrBot 的插件目录即可。

## 目录结构

```
astrbot_plugin_text2image/
├── main.py              # 主逻辑
├── text_renderer.py     # 文本渲染器
├── fonts/               # 字体文件目录 (放置 .ttf/.otf/.ttc)
└── test_renderer.py     # 测试文件
```

**重要**：将字体文件（.ttf/.otf/.ttc）放入 `fonts/` 目录。

## 使用方法

### 基本命令

| 命令 | 说明 |
|------|------|
| `texttool help` | 显示帮助信息 |
| `texttool pm` | 参数说明 |
| `texttool list` | 分页查看可用字体列表 |
| `texttool listall` | 查看所有可用字体（图片形式） |
| `texttool generate <参数> <文本>` | 生成图片 |

### 生成图片

```
texttool generate <文本>
```

示例：
```
texttool generate 你好世界
```

### 参数说明

参数格式：`参数名:值`，多个参数用空格分隔

| 参数 | 说明 | 示例 |
|------|------|------|
| `font` | 字体名称或编号，使用 `texttool list` 查看 | `font:宋体` 或 `font:1` |
| `mode` | 渲染模式 | 见下方 |
| `css` | 自定义 CSS 样式，值含空格时用引号包裹 | `css:color:red;font-size:80px` 或 `css:"color:red;font-family:微软雅黑"` |

#### 渲染模式 (mode)

- `single`（默认）：整行渲染
- `char`：按单个字符渲染
- `word`：按单词渲染（空格分隔）
- `line`：按行渲染
- `token`：按 `|` 分隔渲染

### CSS 自定义

可以使用 `css:` 参数自定义样式：

```
texttool generate css:color:#FF0000;font-size:100px;font-weight:bold 你好
```

支持的 CSS 属性：
- `color` - 文字颜色
- `font-size` - 字体大小
- `font-weight` - 字重（bold/normal）
- `font-family` - 字体族
- `text-shadow` - 文字阴影
- 等等任何 CSS 属性

### 示例

```
# 简单使用
texttool generate Hello World

# 指定字体（名称或编号）
texttool generate font:黑体 你好
texttool generate font:1 你好

# CSS 样式（值含空格时用引号包裹）
texttool generate css:color:red;font-size:120px 警告
texttool generate css:"color:red;font-family:微软雅黑" 你好

# 多行渲染
texttool generate mode:line 第一行\n第二行\n第三行

# 逐字渲染
texttool generate mode:char 你好世界
```

### 查看字体列表

```
# 文字列表（分页）
texttool list

# 图片形式查看所有字体（首次需要缓存）
texttool listall
```

## 配置

在 AstrBot 管理界面配置：

- **默认字体**：不填时使用的字体
- **每页显示字体数量**：`listall` 图片分页数量
- **单次最大字符数**：防止生成过多
- **单次最大图片数**：防止刷屏
- **黑名单**：禁用的群号

## 字体说明

本插件使用 **base64 内嵌** 方式加载字体，无需担心跨域或路径问题。只需将字体文件放入 `fonts/` 目录即可自动识别。

支持的格式：
- `.ttf` - TrueType Font
- `.otf` - OpenType Font
- `.ttc` - TrueType Collection

## 依赖

- playwright
- Pillow

## 鸣谢

- 基于 Playwright Chromium 渲染
- MiniMax-M2.5